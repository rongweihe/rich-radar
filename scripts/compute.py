#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RICH Crypto * Stock 带血筹码雷达 — 数据抓取与信号计算
用于 GitHub Actions 周级更新，生成 data/latest.json（与浏览器端 index.html 内联算法一致）。

数据源（全部免费、无需 API Key）：
  - 加密：Gate.io 公开现货 1d K 线   https://api.gateio.ws/api/v4/spot/candlesticks
  - 美股：Yahoo Finance chart API 1d  https://query1.finance.yahoo.com/v8/finance/chart/<sym>
  - 加密情绪：Alternative.me F&G      https://api.alternative.me/fng/
  - 美股情绪：CBOE VIX (Yahoo ^VIX)

设计原则（对应用户要求）：
  - 恐慌分数只触发进一步研究，不是买入信号。
  - 不编造目标价与概率：obs_price 仅为“重新评估的观察位”，回测 fwd30 为历史真实前瞻收益样本，样本量一并给出。
  - 阈值未经充分历史检验 → 全部写入 config.scoring 并在页面标注“观察提醒”。
  - 每个资产标注数据时间、来源、缺失项。
"""
import json, os, sys, time, math, urllib.request, urllib.error
from datetime import datetime, timezone
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))

UA = {"User-Agent": "Mozilla/5.0 (RICH-Radar; +https://github.com/%s/%s)" % (CFG["github_user"], CFG["repo"])}

SC = {
    "dd_full": {"crypto": 0.50, "stock": 0.35}, "dd_start": 0.10,
    "volr_start": 1.0, "volr_full": 2.5,
    "fng_full": 10, "fng_zero": 40, "vix_zero": 15, "vix_full": 35,
    "obs_dd": {"crypto": 0.40, "stock": 0.25},
    "research_trigger": 60, "attention": 40,
    "thin_qv": 20_000_000,
}


def http_json(url, tries=4, pause=2.0):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa
            last = e
            time.sleep(pause * (i + 1))
    raise RuntimeError("fetch failed %s: %s" % (url, last))


def sigfig(x, n=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    if x == 0:
        return 0
    return float(f"%.{n}g" % x)


def pct(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(x * 1000) / 10


def clamp(x, a, b):
    return max(a, min(b, x))


def dstr(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def get_gate(pair):
    url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=1d&limit=400"
    j = http_json(url)
    rows = []
    for k in j:
        rows.append({"d": dstr(int(k[0])), "c": float(k[2]), "h": float(k[3]),
                     "l": float(k[4]), "v": float(k[1]), "done": k[7] == "true"})
    return rows


def get_yahoo(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d"
    j = http_json(url)
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(res["timestamp"]):
        c = q["close"][i]
        if c is None:
            continue
        rows.append({"d": dstr(ts), "c": c, "h": q["high"][i], "l": q["low"][i],
                     "v": q["volume"][i] or 0, "done": True})
    meta = {"price": res["meta"].get("regularMarketPrice"),
            "time": res["meta"].get("regularMarketTime"),
            "name": res["meta"].get("longName") or res["meta"].get("shortName")}
    return rows, meta


def get_fng():
    j = http_json("https://api.alternative.me/fng/?limit=400")
    return {dstr(int(d["timestamp"])): int(d["value"]) for d in j["data"]}


def rsi(closes, n=14):
    if len(closes) < n + 2:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def components(rows, i, p, kind, sent_at):
    start = max(0, i - 364)
    win = rows[start:i + 1]
    hi = max(x["c"] for x in win)
    dd = p / hi - 1
    A = 25 * clamp((-dd - SC["dd_start"]) / (SC["dd_full"][kind] - SC["dd_start"]), 0, 1)
    r7 = p / rows[i - 7]["c"] - 1 if i >= 7 else None
    B = 0.0; pr = None
    if r7 is not None and i >= 37:
        hist = [rows[k]["c"] / rows[k - 7]["c"] - 1 for k in range(7, i + 1)]
        pr = sum(1 for x in hist if x <= r7) / len(hist)
        B = 25 * clamp((0.2 - pr) / 0.2, 0, 1)
    C = 0.0; vr = None
    if i >= 30:
        v7 = [x["v"] for x in rows[max(0, i - 6):i + 1]]
        v90 = [x["v"] for x in rows[max(0, i - 89):i + 1]]
        med = median(v90)
        if med > 0:
            vr = (sum(v7) / len(v7)) / med
            C = 25 * clamp((vr - SC["volr_start"]) / (SC["volr_full"] - SC["volr_start"]), 0, 1)
    D = 0.0; sv = sent_at(rows[i]["d"])
    if sv is not None:
        if kind == "crypto":
            D = 25 * clamp((SC["fng_zero"] - sv) / (SC["fng_zero"] - SC["fng_full"]), 0, 1)
        else:
            D = 25 * clamp((sv - SC["vix_zero"]) / (SC["vix_full"] - SC["vix_zero"]), 0, 1)
    return {"A": sigfig(A, 3), "B": sigfig(B, 3), "C": sigfig(C, 3), "D": sigfig(D, 3),
            "score": round(A + B + C + D), "dd": dd, "hi": hi, "r7": r7, "pr": pr, "vr": vr, "sv": sv}


def analyze(rows_all, kind, sent_at, live_price=None):
    rows = [x for x in rows_all if x["done"]]
    i = len(rows) - 1
    p = live_price if live_price is not None else rows[i]["c"]
    comp = components(rows, i, p, kind, sent_at)
    c = [x["c"] for x in rows]
    win = rows[max(0, i - 364):]
    hi_row = max(win, key=lambda x: x["c"])
    lo_row = min(win, key=lambda x: x["c"])
    lo60 = min(x["c"] for x in rows[max(0, i - 59):])
    ma200 = sum(c[-200:]) / 200 if len(c) >= 200 else None
    ma50 = sum(c[-50:]) / 50 if len(c) >= 50 else None
    rv = None
    if len(c) > 31:
        lr = [math.log(c[k] / c[k - 1]) for k in range(len(c) - 30, len(c))]
        m = sum(lr) / len(lr)
        sd = math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1))
        rv = sd * math.sqrt(365 if kind == "crypto" else 252)
    peak = -1e18; mdd = 0.0
    for x in win:
        peak = max(peak, x["c"]); mdd = min(mdd, x["c"] / peak - 1)
    # lite backtest
    days_ge60 = days_ge40 = triggers = 0; score_max = 0; fwd30 = []
    prev_score = 0
    for k in range(90, i + 1):
        ck = components(rows, k, rows[k]["c"], kind, sent_at)
        score_max = max(score_max, ck["score"])
        if ck["score"] >= 60:
            days_ge60 += 1
        if ck["score"] >= 40:
            days_ge40 += 1
        if ck["score"] >= 60 and prev_score < 60:
            triggers += 1
            if k + 30 <= i:
                fwd30.append(rows[k + 30]["c"] / rows[k]["c"] - 1)
        prev_score = ck["score"]
    fwd = None
    if fwd30:
        fwd = {"n": len(fwd30), "median": sigfig(median(fwd30), 3),
               "min": sigfig(min(fwd30), 3), "max": sigfig(max(fwd30), 3)}
    obs = min(lo60 * 0.97, hi_row["c"] * (1 - SC["obs_dd"][kind]))
    out = {
        "price": sigfig(p, 6), "last_bar": rows[i]["d"], "bars": len(rows), "first_bar": rows[0]["d"],
        "ret_1d": pct(p / rows[i - 1]["c"] - 1), "ret_7d": pct(comp["r7"]),
        "ret_30d": pct(p / rows[i - 30]["c"] - 1) if i >= 30 else None,
        "ret_90d": pct(p / rows[i - 90]["c"] - 1) if i >= 90 else None,
        "ret_1d_prevbar": pct(rows[i]["c"] / rows[i - 1]["c"] - 1),
        "high_1y": sigfig(hi_row["c"], 6), "high_1y_date": hi_row["d"],
        "low_1y": sigfig(lo_row["c"], 6), "low_1y_date": lo_row["d"],
        "dd_from_high": pct(comp["dd"]), "up_from_low": pct(p / lo_row["c"] - 1),
        "range_pos": pct((p - lo_row["c"]) / (hi_row["c"] - lo_row["c"])),
        "low_60": sigfig(lo60, 6), "ma50": sigfig(ma50, 6), "ma200": sigfig(ma200, 6),
        "vs_ma200": pct(p / ma200 - 1) if ma200 else None,
        "rsi14": sigfig(rsi((c + ([p] if live_price else []))[-120:], 14), 3),
        "rvol30": pct(rv), "mdd_1y": pct(mdd),
        "r7_pctile": pct(comp["pr"]), "vol_ratio": sigfig(comp["vr"], 3), "sentiment": comp["sv"],
        "score": comp["score"], "comps": {"drawdown": comp["A"], "shock": comp["B"],
                                          "volume": comp["C"], "sentiment": comp["D"]},
        "obs_price": sigfig(obs, 6), "obs_gap": pct(obs / p - 1),
        "backtest": {"days": (i - 90 + 1), "days_ge60": days_ge60, "days_ge40": days_ge40,
                     "score_max": score_max, "triggers": triggers, "fwd30": fwd},
        "spark": [sigfig(x["c"], 5) for x in rows[-120:]],
    }
    return out


def main():
    import urllib.parse  # noqa
    globals()["urllib"].parse = urllib.parse
    fng = get_fng()
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(),
           "generator": "scripts/compute.py v1", "assets": {}, "bench": {}, "errors": []}

    # VIX first (for stock sentiment)
    vix_map = {}
    try:
        vrows, vmeta = get_yahoo("^VIX")
        for x in vrows:
            vix_map[x["d"]] = x["c"]
        out["bench"]["VIX"] = {"price": sigfig(vmeta["price"], 4), "time": dstr(vmeta["time"]),
                               "hist30": [sigfig(x["c"], 4) for x in vrows[-30:]],
                               "high_1y": sigfig(max(x["c"] for x in vrows), 4),
                               "low_1y": sigfig(min(x["c"] for x in vrows), 4)}
    except Exception as e:
        out["errors"].append("VIX %s" % e)

    def vix_at(d):
        if d in vix_map:
            return vix_map[d]
        ks = sorted(k for k in vix_map if k <= d)
        return vix_map[ks[-1]] if ks else None

    def fng_at(d):
        return fng.get(d)

    for pair in CFG["watchlist"]["crypto"]:
        try:
            rows = get_gate(pair)
            live = None if rows[-1]["done"] else rows[-1]["c"]
            a = analyze(rows, "crypto", fng_at, live)
            a.update({"kind": "crypto",
                      "source": "Gate.io spot 1d candlesticks (quote volume USDT)",
                      "live_bar": rows[-1]["d"]})
            v90 = median([x["v"] for x in rows[-90:] if x["done"]])
            if v90 < SC["thin_qv"]:
                a["flags"] = ["thin_liquidity"]
            out["assets"][pair] = a
        except Exception as e:
            out["errors"].append("%s %s" % (pair, e))

    for sym in CFG["watchlist"]["stocks"]:
        try:
            rows, meta = get_yahoo(sym)
            a = analyze(rows, "stock", vix_at, None)
            a.update({"kind": "stock", "name": meta["name"],
                      "source": "Yahoo Finance chart API 1d (share volume)",
                      "market_time": datetime.fromtimestamp(meta["time"], tz=timezone.utc).isoformat()})
            out["assets"][sym] = a
        except Exception as e:
            out["errors"].append("%s %s" % (sym, e))

    for sym in ["SPY", "QQQ"]:
        try:
            rows, meta = get_yahoo(sym)
            a = analyze(rows, "stock", vix_at, None)
            out["bench"][sym] = {"price": a["price"], "last_bar": a["last_bar"],
                                 "ret_1d": a["ret_1d"], "ret_7d": a["ret_7d"], "ret_30d": a["ret_30d"],
                                 "dd_from_high": a["dd_from_high"], "vs_ma200": a["vs_ma200"],
                                 "rvol30": a["rvol30"], "spark": a["spark"][-30:]}
        except Exception as e:
            out["errors"].append("%s %s" % (sym, e))

    last_fng_day = sorted(fng)[-1]
    out["fng"] = {"value": fng[last_fng_day], "date": last_fng_day,
                  "hist30": [fng[d] for d in sorted(fng)[-30:]]}
    out["missing"] = [
        "Stooq 不可用（Access denied），美股改用 Yahoo Finance",
        "美股历史仅 1 年（约 251 交易日），恐慌分数回测样本约 161 天",
        "部分小市值币（如 LINK）在单一交易所成交量偏薄，成交量分量可信度低",
        "加密情绪分量按最后完整日的 F&G 取值",
        "无链上数据、无期权/资金费率、无自动基本面财报抓取",
    ]

    dst = os.path.join(ROOT, "data", "latest.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    # append to history (one snapshot per run, keep last 400)
    hist_path = os.path.join(ROOT, "data", "history.json")
    hist = []
    if os.path.exists(hist_path):
        try:
            hist = json.load(open(hist_path, encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({"t": out["fetched_at"], "fng": out["fng"]["value"],
                 "scores": {k: v["score"] for k, v in out["assets"].items()}})
    hist = hist[-400:]
    json.dump(hist, open(hist_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("OK assets=%d errors=%d fng=%s" % (len(out["assets"]), len(out["errors"]), out["fng"]["value"]))
    if out["errors"]:
        print("ERRORS:", out["errors"], file=sys.stderr)


if __name__ == "__main__":
    main()
