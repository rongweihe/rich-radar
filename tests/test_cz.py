"""Offline failure-oriented tests; no real X account or network is used."""
import asyncio
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cz_rules import analyze_post
from cz_sources import normalize_tweet, fetch_twscrape, fetch_rss, validate_post
from compute_cz import initial_snapshot, merge_snapshot, collect
from refresh import due, due_slot, run_task
from build_site import build, FILES
from verify_site import verify

NOW = "2025-01-01T01:00:00+00:00"
CFG = {"username": "cz_binance", "retain_posts": 300, "retention_days": 90, "alert_max_age_minutes": 60}


def post(identifier="100", text="Bitcoin dips are the best opportunity to buy.", **kwargs):
    return {"id": identifier, "author": "cz_binance", "text": text,
            "published_at": "2025-01-01T00:50:00+00:00", "kind": "original", "has_media": False,
            "text_complete": True, "edit_ids": [], **kwargs}


def result(posts, source="twscrape", status="ok", **kwargs):
    return {"source": source, "status": status, "code": "ok" if status == "ok" else "source_error", "posts": posts, **kwargs}


class RulesTests(unittest.TestCase):
    def test_positive_and_implicit_examples(self):
        for text, level in [
            ("Bitcoin dips are the best opportunity to buy.", "explicit"),
            ("比特币完蛋了？这些时刻都是最佳买入机会。", "explicit"),
            ("Every dip is an opportunity.", "opportunity"),
            ("每一次下跌都是机会。", "opportunity"),
            ("You will thank yourself in two years for what you do today.", "implicit"),
            ("如果你希望两年后的自己感谢今天的所作所为，那么你应该……", "implicit"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(analyze_post(post(text=text))["level"], level)

    def test_negation_and_noise(self):
        for text in ["Don't buy BTC.", "Do not buy Bitcoin.", "现在不要买入比特币", "这不是最佳买入机会"]:
            self.assertEqual(analyze_post(post(text=text))["level"], "excluded")
        self.assertEqual(analyze_post(post(text="BTC"))["level"], "none")
        for text in ("Happy new year!", "10 years ago I moved here.", "祝你未来一切顺利"):
            self.assertEqual(analyze_post(post(text=text))["level"], "none")
        self.assertEqual(analyze_post(post(text="Best opportunity for a giveaway! Buy Bitcoin"))["level"], "excluded")

    def test_unknown_metadata_and_quotes_are_not_high_confidence(self):
        for change in ({"kind": "quote"}, {"kind": "unknown"}, {"text_complete": None}):
            self.assertEqual(analyze_post(post(**change))["level"], "review")
        self.assertEqual(analyze_post(post(kind="retweet"))["level"], "excluded")
        self.assertFalse(analyze_post(post(has_media=None))["text_style"])


class SnapshotTests(unittest.TestCase):
    def seed(self):
        return merge_snapshot(initial_snapshot(), [result([post()], user_id="42")], CFG, NOW)

    def test_baseline_then_overlap_and_new_post(self):
        first = self.seed()
        self.assertEqual(first["status"], "degraded")
        self.assertTrue(first["posts"][0]["backfill"])
        second = merge_snapshot(first, [result([post("101"), post()])], CFG, "2025-01-01T01:15:00+00:00")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["sources"]["twscrape"]["anchor_id"], "101")
        self.assertFalse(second["posts"][0]["backfill"])

    def test_gap_never_advances_anchor_and_can_recover(self):
        first = self.seed()
        gap = merge_snapshot(first, [result([post("105")])], CFG, NOW)
        self.assertEqual(gap["status"], "degraded")
        self.assertEqual(gap["sources"]["twscrape"]["anchor_id"], "100")
        fixed = merge_snapshot(gap, [result([post("105"), post()])], CFG, NOW)
        self.assertEqual(fixed["status"], "ok")

    def test_failure_retains_data_time_and_adds_backoff(self):
        first = self.seed()
        failed = merge_snapshot(first, [result([], status="error")], CFG, "2025-01-01T01:15:00+00:00")
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["last_success_at"], NOW)
        self.assertEqual(failed["posts"], first["posts"])
        self.assertEqual(failed["sources"]["twscrape"]["retry_after"], "2025-01-01T01:30:00+00:00")
        with patch('compute_cz.fetch_twscrape') as fetch:
            results = collect(CFG, failed, {"CZ_X_COOKIES": "secret"}, "2025-01-01T01:16:00+00:00")
            fetch.assert_not_called()
            self.assertEqual(results[0]["status"], "cooldown")

    def test_empty_and_partial_results_are_not_healthy(self):
        first = self.seed()
        for r in (result([]), result([post(), post("101")], status="partial")):
            next_snapshot = merge_snapshot(first, [r], CFG, "2025-01-01T01:15:00+00:00")
            self.assertNotEqual(next_snapshot["status"], "ok")
            self.assertEqual(next_snapshot["last_success_at"], NOW)
            self.assertEqual(next_snapshot["sources"]["twscrape"]["anchor_id"], "100")

    def test_rss_never_claims_full_coverage_or_overwrites_primary(self):
        first = self.seed()
        second = merge_snapshot(first, [result([], status="error"), result([post(text="Short summary"),post("102")],source="rss")], CFG, NOW)
        self.assertEqual(second["status"], "degraded")
        old = next(p for p in second["posts"] if p["id"] == "100")
        self.assertEqual(old["text"], first["posts"][0]["text"])
        self.assertEqual(second["sources"]["rss"]["coverage"], "unknown")

    def test_edit_is_one_record_and_keeps_first_seen(self):
        first = self.seed()
        edited = post("101", "Buy Bitcoin for the long term", edit_ids=["100", "101"])
        second = merge_snapshot(first, [result([edited])], CFG, "2025-01-01T01:15:00+00:00")
        self.assertEqual(len(second["posts"]), 1)
        self.assertTrue(second["posts"][0]["edited"])
        self.assertEqual(second["posts"][0]["first_seen_at"], NOW)
        self.assertEqual(second["status"], "ok")

    def test_dedup_and_retention(self):
        out = merge_snapshot(initial_snapshot(), [result([post("102"),post(),post("102")])], {**CFG,"retain_posts":1}, NOW)
        self.assertEqual([p["id"] for p in out["posts"]], ["102"])

    def test_out_of_order_edit_revisions_never_roll_back(self):
        latest = post("101", "Buy Bitcoin for the long term", edit_ids=["100", "101"])
        for posts in ([latest, post()], [post(), latest]):
            snapshot = merge_snapshot(self.seed(), [result(posts)], CFG, NOW)
            self.assertEqual(len(snapshot["posts"]), 1)
            self.assertEqual(snapshot["posts"][0]["id"], "101")
            again = merge_snapshot(snapshot, [result([post()])], CFG, NOW)
            self.assertEqual(again["posts"][0]["text"], latest["text"])

    def test_invalid_author_and_missing_date_are_rejected(self):
        for p in (post(author="someone_else"), post(published_at="2025-01-01"), post(id="<script>")):
            with self.assertRaises(ValueError):
                validate_post(p, "cz_binance")
        out = merge_snapshot(initial_snapshot(), [result([post(author="spoof")])], CFG, NOW)
        self.assertNotEqual(out["status"], "ok")
        self.assertEqual(out["posts"], [])

    def test_unconfigured_is_explicit_and_has_no_sample_posts(self):
        data = merge_snapshot(initial_snapshot(), collect(CFG, initial_snapshot(), {}, NOW), CFG, NOW)
        self.assertEqual(data["status"], "unconfigured")
        self.assertEqual(data["posts"], [])


class AdapterTests(unittest.TestCase):
    def tweet(self):
        return SimpleNamespace(id=100, user=SimpleNamespace(id=42, username="cz_binance"),
            date=datetime(2025,1,1,tzinfo=timezone.utc), rawContent="Buy Bitcoin",
            media=SimpleNamespace(photos=[], videos=[], animated=[]), retweetedTweet=None,
            inReplyToTweetId=None, isQuoteStatus=False, quotedTweet=None, editControl={})

    def test_normalization_checks_numeric_identity(self):
        self.assertIsNone(normalize_tweet(self.tweet(), "cz_binance", "999"))
        value = normalize_tweet(self.tweet(), "cz_binance", "42")
        self.assertEqual(value["url"], "https://x.com/cz_binance/status/100")
        self.assertFalse(value["has_media"])

    def test_exception_never_leaks_credentials_and_partial_is_retained(self):
        tweet = self.tweet()
        class FakeAPI:
            def __init__(self, *args, **kwargs): self.pool=self
            async def add_account_cookies(self, *args): pass
            async def user_by_login(self, username): return tweet.user
            async def user_tweets(self, *args, **kwargs):
                yield tweet
                raise RuntimeError('auth_token=SECRET_VALUE')
        module=ModuleType('twscrape');module.API=FakeAPI
        log=ModuleType('twscrape.logger');log.set_log_level=lambda level: None
        with patch.dict(sys.modules, {'twscrape':module,'twscrape.logger':log}):
            data=asyncio.run(fetch_twscrape(CFG, {}, 'SECRET_VALUE'))
        self.assertEqual(data['status'], 'partial')
        self.assertEqual(len(data['posts']), 1)
        self.assertNotIn('SECRET_VALUE', json.dumps(data))

    def test_rss_fixture_and_html_text(self):
        try:
            import feedparser  # noqa
        except ImportError:
            self.skipTest('Optional RSS dependency not installed')
        body=b'''<?xml version="1.0"?><rss version="2.0"><channel><title>CZ</title><link>https://x.com/cz_binance</link><description>CZ</description><item><title>Post</title><link>https://x.com/cz_binance/status/123</link><pubDate>Wed, 01 Jan 2025 00:00:00 GMT</pubDate><description><![CDATA[<p>Buy Bitcoin</p><script>alert(1)</script>]]></description></item></channel></rss>'''
        with patch('cz_sources.urllib.request.urlopen',return_value=io.BytesIO(body)):
            data=fetch_rss(CFG,'https://example.com/feed')
        self.assertEqual(data['status'],'ok')
        self.assertEqual(data['posts'][0]['text'],'Buy Bitcoin')
        self.assertIsNone(data['posts'][0]['text_complete'])
        self.assertEqual(data['posts'][0]['kind'],'unknown')


class DeploymentTests(unittest.TestCase):
    def test_fatal_collector_failure_restores_last_snapshot(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "data").mkdir()
            path = root / "data/cz.json"
            original = json.dumps(initial_snapshot()).encode()
            path.write_bytes(original)
            def fail(*args, **kwargs):
                path.write_text('{invalid partial write')
                raise subprocess.TimeoutExpired('compute_cz.py', 150)
            with patch('refresh.ROOT', root), patch('refresh.subprocess.run', side_effect=fail):
                self.assertEqual(run_task('cz'), 'error')
            self.assertEqual(path.read_bytes(), original)

    def test_due_slots_catch_up_and_back_off(self):
        monday=datetime(2025,1,6,1,5,tzinfo=timezone.utc)
        self.assertEqual(due_slot('market',monday),monday.replace(minute=0))
        self.assertTrue(due('market',{},monday))
        self.assertFalse(due('market',{'slot':due_slot('market',monday).isoformat()},monday))
        self.assertFalse(due('ema',{'last_attempt_at':monday.isoformat()},monday))

    def test_allowlist_excludes_sessions_and_live_hash_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(initial_snapshot()) if name=='data/cz.json' else '{}' if name.endswith('.json') else 'test')
            (root/'accounts.db').write_text('SECRET')
            build(root)
            self.assertFalse((root/'_site/accounts.db').exists())
            def live(req, **kwargs):
                name=req.full_url.split('https://example.com/radar/')[1].split('?')[0]
                return io.BytesIO((root/'_site'/name).read_bytes())
            with patch('verify_site.urllib.request.urlopen',side_effect=live):
                verify('https://example.com/radar/',root/'_site',attempts=1)
            with patch('verify_site.urllib.request.urlopen',return_value=io.BytesIO(b'{}')):
                with self.assertRaises(RuntimeError):
                    verify('https://example.com/radar/',root/'_site',attempts=1)


if __name__ == '__main__':
    unittest.main()
