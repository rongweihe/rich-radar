"""验证金融指标口径、收盘边界及前后端一致性；无需额外测试依赖。"""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compute_ema import analyze_ema, ema_series, yahoo_closed_rows
import compute_ema


def rows(prices):
    start = date(2025, 1, 1)
    return [{"d": (start + timedelta(days=i)).isoformat(), "c": price, "done": True}
            for i, price in enumerate(prices)]


class EMATests(unittest.TestCase):
    def test_sma_seed_and_known_recurrence(self):
        self.assertEqual(ema_series([10, 20, 30, 40, 50], 3), [None, None, 20, 30, 40])

    def test_insufficient_history_keeps_fast_ema(self):
        result = analyze_ema(rows([100] * 199), "crypto")
        self.assertEqual(result["state"], "insufficient")
        self.assertEqual(result["ema20"], 100)
        self.assertIsNone(result["ema200"])
        self.assertEqual(result["above_bars"], 0)

    def test_equal_does_not_trigger(self):
        result = analyze_ema(rows([100] * 200), "crypto")
        self.assertEqual(result["state"], "equal")
        self.assertFalse(result["just_crossed"])

    def test_confirmed_cross_and_duration(self):
        first = analyze_ema(rows([100] * 200 + [110]), "crypto")
        self.assertTrue(first["just_crossed"])
        self.assertEqual(first["above_bars"], 1)
        second = analyze_ema(rows([100] * 200 + [110, 110]), "crypto")
        self.assertEqual(second["above_bars"], 2)
        self.assertEqual(second["calendar_days"], 2)
        self.assertFalse(second["lower_bound"])
        self.assertFalse(second["just_crossed"])
        self.assertGreater(second["gap_pct"], 0)

    def test_break_resets_streak_and_recross_starts_at_one(self):
        broken = rows([100] * 200 + [110, 110, 1])
        self.assertEqual(analyze_ema(broken, "crypto")["above_bars"], 0)
        result = analyze_ema(rows([100] * 200 + [110, 110, 1, 300]), "crypto")
        self.assertEqual(result["above_bars"], 1)
        self.assertTrue(result["just_crossed"])

    def test_window_boundary_is_a_lower_bound(self):
        result = analyze_ema(rows(list(range(1, 202))), "crypto")
        self.assertEqual(result["above_bars"], 2)
        self.assertTrue(result["lower_bound"])
        self.assertFalse(result["just_crossed"])

    def test_unclosed_bar_never_changes_signal(self):
        history = rows([100] * 200)
        intraday = rows([100] * 200 + [1000])[-1]
        intraday["done"] = False
        self.assertEqual(analyze_ema(history + [intraday], "crypto"), analyze_ema(history, "crypto"))

    def test_stock_weekend_counts_trading_bars_and_calendar_span(self):
        history = rows([100] * 200 + [110, 110])
        history[-2]["d"], history[-1]["d"] = "2025-07-25", "2025-07-28"
        result = analyze_ema(history, "stock")
        self.assertEqual(result["above_bars"], 2)
        self.assertEqual(result["calendar_days"], 4)

    def test_ordering_and_deduplication(self):
        history = rows([100] * 200 + [110, 110])
        self.assertEqual(analyze_ema(list(reversed(history)) + [history[-1]], "crypto"), analyze_ema(history, "crypto"))

    def test_invalid_data_and_gaps_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                analyze_ema(rows([value]), "crypto")
        with self.assertRaises(ValueError):
            analyze_ema(rows([100] * 201)[1:100] + rows([100] * 201)[101:], "crypto")
        with self.assertRaises(ValueError):
            analyze_ema([], "crypto")

    def test_yahoo_intraday_close_and_weekend(self):
        def ts(value):
            return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
        result = {"meta": {"exchangeTimezoneName": "America/New_York", "currentTradingPeriod": {
            "regular": {"end": ts("2026-10-02T20:00:00")}}},
            "timestamp": [ts("2026-10-01T13:30:00"), ts("2026-10-02T13:30:00")],
            "indicators": {"quote": [{"close": [100, 110]}]}}
        self.assertEqual([r["done"] for r in yahoo_closed_rows(result, ts("2026-10-02T19:00:00"))], [True, False])
        self.assertEqual([r["done"] for r in yahoo_closed_rows(result, ts("2026-10-02T20:06:00"))], [True, True])
        self.assertEqual([r["done"] for r in yahoo_closed_rows(result, ts("2026-10-03T12:00:00"))], [True, True])
        result["meta"]["currentTradingPeriod"] = {}
        self.assertFalse(yahoo_closed_rows(result, ts("2026-10-02T20:06:00"))[-1]["done"])

    def test_source_failure_preserves_original_asset_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data" / "ema.json"
            target.parent.mkdir()
            old = {"kind": "stock", "last_bar": "2025-07-25", "fetched_at": "2025-07-26T00:00:00Z"}
            target.write_text(json.dumps({"assets": {"CRCL": old}}))
            config = {"ema_radar": {"crypto": ["BTC_USDT"], "stocks": ["CRCL"]}}
            with patch.object(compute_ema, "ROOT", directory), patch.object(compute_ema, "CFG", config), \
                 patch.object(compute_ema, "fetch_crypto", return_value=(rows([100] * 201), "test")), \
                 patch.object(compute_ema, "fetch_stock", side_effect=RuntimeError("HTTP 429")), \
                 patch("builtins.print"):
                compute_ema.main()
            snapshot = json.loads(target.read_text())
            self.assertEqual(snapshot["assets"]["CRCL"], old)
            self.assertEqual(snapshot["errors"], [{"symbol": "CRCL", "message": "HTTP 429"}])
            self.assertIn("BTC_USDT", snapshot["assets"])

    def test_browser_gate_closed_flag_and_day_boundary(self):
        # 即使源误标已收盘，当天 UTC 日 K 仍不能进入确认指标。
        script = """
const assert=require('node:assert/strict'),radar=require('./scripts/ema-radar.js');
const now=Date.parse('2026-10-07T08:00:00Z');
const raw=[['1791158400','1','100','100','100','100','1','true'],
           ['1791244800','1','110','110','110','110','1','false'],
           ['1791331200','1','120','120','120','120','1','true']];
assert.deepEqual(radar.gateRows(raw,now).map(r=>r.done),[true,false,false]);
assert.throws(()=>radar.analyze([{d:'2026-02-30',c:100,done:true}],'crypto'));
"""
        subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, check=True)

    def test_python_and_browser_produce_identical_results(self):
        fixtures = [{"rows": rows(prices), "kind": "crypto"} for prices in (
            [100] * 19, [100] * 199, [100] * 200, [100] * 200 + [110],
            [100] * 200 + [110, 110, 1, 300], list(range(1, 1001)),
            [100 + 20 * math.sin(i / 15) for i in range(1000)])]
        stock = rows([100] * 200 + [110, 110])
        stock[-2]["d"], stock[-1]["d"] = "2025-07-25", "2025-07-28"
        fixtures.append({"rows": stock, "kind": "stock"})
        script = "const fs=require('node:fs'),r=require('./scripts/ema-radar.js'); const f=JSON.parse(fs.readFileSync(0,'utf8')); process.stdout.write(JSON.stringify(f.map(x=>r.analyze(x.rows,x.kind))));"
        result = subprocess.run(["node", "-e", script], input=json.dumps(fixtures), text=True,
                                cwd=ROOT, capture_output=True, check=True)
        browser = json.loads(result.stdout)
        for fixture, actual in zip(fixtures, browser):
            self.assertEqual(actual, analyze_ema(fixture["rows"], fixture["kind"]))


if __name__ == "__main__":
    unittest.main()
