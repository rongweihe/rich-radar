#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立刷新均线雷达，不改动恐慌评分或原观察名单。"""
import json
import math
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from compute import CFG, ROOT, dstr, http_json


def ema_series(closes, period):
    """用首 N 根收盘均价初始化，避免首根价格对长周期 EMA 产生过大偏差。"""
    values = [None] * len(closes)
    if len(closes) < period:
        return values
    values[period - 1] = sum(closes[:period]) / period
    alpha = 2 / (period + 1)
    for i in range(period, len(closes)):
        values[i] = closes[i] * alpha + values[i - 1] * (1 - alpha)
    return values


def analyze_ema(rows_all, kind):
    # 按日期去重排序，保证交易所返回倒序或重复 K 线时不会重复累计持续天数。
    by_day = {}
    for row in rows_all:
        if row.get("done") is not True:
            continue
        datetime.strptime(row["d"], "%Y-%m-%d")
        if not isinstance(row["c"], (int, float)) or not math.isfinite(row["c"]) or row["c"] <= 0:
            raise ValueError("已收盘 K 线价格无效")
        by_day[row["d"]] = row
    rows = [by_day[d] for d in sorted(by_day)]
    if not rows:
        raise ValueError("没有已收盘日 K")
    # 加密每天交易，缺失日不能默认为连续；拒绝不完整历史以免发出虚假信号。
    if kind == "crypto" and any(
        (datetime.fromisoformat(b["d"]) - datetime.fromisoformat(a["d"])).days != 1
        for a, b in zip(rows, rows[1:])
    ):
        raise ValueError("日 K 历史存在缺口")
    closes = [r["c"] for r in rows]
    fast, slow = ema_series(closes, 20), ema_series(closes, 200)
    last = len(rows) - 1
    state = "insufficient"
    count, lower_bound, crossed, since, calendar_days = 0, False, False, None, 0
    if slow[last] is not None:
        state = "above" if fast[last] > slow[last] else "below" if fast[last] < slow[last] else "equal"
        if state == "above":
            start = last
            while start >= 199 and fast[start] > slow[start]:
                start -= 1
            count = last - start
            # EMA200 初始化之前无法判断关系；不能把可见窗口开头伪称为上穿日期。
            lower_bound = start < 199
            since = rows[start + 1]["d"]
            crossed = count == 1 and not lower_bound
            calendar_days = (datetime.fromisoformat(rows[last]["d"]) - datetime.fromisoformat(since)).days + 1
    return {
        "kind": kind, "last_bar": rows[last]["d"], "first_bar": rows[0]["d"], "bars": len(rows),
        "close": closes[last], "ema20": fast[last], "ema200": slow[last], "state": state,
        "gap_pct": (fast[last] / slow[last] - 1) * 100 if slow[last] else None,
        "above_bars": count, "calendar_days": calendar_days, "above_since": since,
        "lower_bound": lower_bound, "just_crossed": crossed,
        "chart": [{"d": rows[i]["d"], "ema20": fast[i], "ema200": slow[i]} for i in range(max(199, last - 59), last + 1)],
    }


def fetch_crypto(pair):
    limit = CFG["ema_radar"]["history_bars"]
    data = http_json(f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=1d&limit={limit}", tries=2)
    if not isinstance(data, list):
        raise ValueError("Gate 返回无效 K 线数据")
    now = time.time()
    # 同时检查收盘标记与 UTC 日边界，防止当天未完成 K 线混入确认信号。
    rows = [{"d": dstr(k[0]), "c": float(k[2]),
             "done": str(k[7]).lower() == "true" and int(k[0]) + 86400 <= now} for k in data]
    return rows, "Gate.io · 现货日 K · USDT"


def yahoo_closed_rows(result, now=None):
    """使用交易所时区和当日收盘时间排除盘中日 K，周末保留最近交易日。"""
    now = time.time() if now is None else now
    meta = result["meta"]
    tz = ZoneInfo(meta.get("exchangeTimezoneName", "America/New_York"))
    today = datetime.fromtimestamp(now, tz).date()
    end = meta.get("currentTradingPeriod", {}).get("regular", {}).get("end")
    closes = result["indicators"]["quote"][0]["close"]
    rows = []
    for ts, close in zip(result.get("timestamp", []), closes):
        day = datetime.fromtimestamp(ts, tz).date()
        # 缺少收盘时间时对当日采取保守策略，避免把最新成交价当作收盘价。
        done = day < today or (day == today and end is not None and now >= end + 300)
        if close is not None:
            rows.append({"d": day.isoformat(), "c": close, "done": done})
    return rows


def fetch_stock(sym):
    data = http_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=5y&interval=1d", tries=2)
    result = data["chart"]["result"][0]
    return yahoo_closed_rows(result), "Yahoo Finance · 美股日 K · USD"


def main():
    dst = os.path.join(ROOT, "data", "ema.json")
    previous = {}
    if os.path.exists(dst):
        with open(dst, encoding="utf-8") as file:
            previous = json.load(file).get("assets", {})
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(), "assets": {}, "errors": []}
    successes = 0
    for kind, symbols in [("crypto", CFG["ema_radar"]["crypto"]), ("stock", CFG["ema_radar"]["stocks"])]:
        for sym in symbols:
            try:
                rows, source = fetch_crypto(sym) if kind == "crypto" else fetch_stock(sym)
                asset = analyze_ema(rows, kind)
                asset.update({"source": source, "fetched_at": datetime.now(timezone.utc).isoformat()})
                out["assets"][sym] = asset
                successes += 1
            except Exception as error:
                # 单个源失败保留带原时间的快照，并显式记录失败，避免清空或冒充更新成功。
                if sym in previous:
                    out["assets"][sym] = previous[sym]
                out["errors"].append({"symbol": sym, "message": str(error)})
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst + ".tmp", "w", encoding="utf-8") as file:
        json.dump(out, file, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(dst + ".tmp", dst)
    print(f"EMA radar: updated={successes}, errors={len(out['errors'])}")
    if out["errors"]:
        print(json.dumps(out["errors"], ensure_ascii=False), file=sys.stderr)
    if successes == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
