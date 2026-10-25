#!/usr/bin/env python3
"""Collect, classify and atomically persist a bounded CZ snapshot (no credentials)."""
import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cz_rules import analyze_post, RULE_VERSION
from cz_sources import fetch_twscrape, fetch_rss, parse_time, validate_post, utcnow

ROOT = Path(__file__).resolve().parents[1]
SIGNALS = {"explicit", "opportunity", "implicit", "review"}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def initial_snapshot(username="cz_binance"):
    return {"schema_version": 1, "snapshot_id": "unconfigured", "username": username,
            "generated_at": None, "last_success_at": None, "status": "unconfigured",
            "rule_version": RULE_VERSION, "sources": {}, "posts": []}


def canonical_id(post):
    return min(post.get("edit_ids", []) + [post["id"]], key=int)


def merge_snapshot(previous, results, config, now=None):
    now = now or utcnow()
    now_dt = parse_time(now)
    previous = previous if previous.get("username") == config["username"] else initial_snapshot(config["username"])
    out = {**previous, "generated_at": now, "rule_version": RULE_VERSION,
           "sources": {k: dict(v) for k, v in previous.get("sources", {}).items()}}
    records = {canonical_id(p): dict(p) for p in previous.get("posts", [])}
    aliases = {alias: key for key, p in records.items() for alias in p.get("edit_ids", []) + [p["id"]]}
    baseline = not previous.get("last_success_at")
    statuses = []
    for result in results:
        name = result["source"]
        old = out["sources"].get(name, {})
        state = dict(old)
        state["status"], state["code"] = result["status"], result["code"]
        if result["status"] in ("unconfigured", "disabled", "cooldown"):
            out["sources"][name] = state
            statuses.append(state["status"])
            continue
        state["last_attempt_at"] = now
        posts, invalid = [], False
        for post in result.get("posts", []):
            try:
                posts.append(validate_post(post, config["username"]))
            except (ValueError, KeyError, TypeError):
                invalid = True
        if invalid:
            state.update(status="partial", code="invalid_items")
        if not posts and state["status"] == "ok":
            state.update(status="error", code="empty_response")
        if result.get("user_id"):
            state["user_id"] = result["user_id"]
        if posts:
            state["latest_post_at"] = max(p["published_at"] for p in posts)
            # RSS does not expose reliable paging/completeness. Never promote to healthy.
            seen = {x for p in posts for x in [p["id"]] + p.get("edit_ids", [])}
            anchor = old.get("anchor_id")
            coverage = "unknown" if name == "rss" else "baseline" if not anchor else "overlap" if anchor in seen else "gap"
            state["coverage"] = coverage
            if state["status"] == "ok":
                state["last_success_at"] = now
                out["last_success_at"] = now
                if name != "rss" and coverage != "gap":
                    newest = max(posts, key=lambda p: (p["published_at"], int(p["id"])))
                    state["anchor_id"] = newest["id"]
            for post in posts:
                key = next((aliases[x] for x in [post["id"]] + post.get("edit_ids", []) if x in aliases), canonical_id(post))
                old_post = records.get(key)
                # A secondary summary must not overwrite richer primary text.
                if old_post and old_post.get("source") == "twscrape" and name == "rss":
                    continue
                # Timelines can return both edit revisions, newest first. Never let
                # an older revision overwrite the newer text already persisted.
                if old_post and int(post["id"]) < int(old_post["id"]):
                    continue
                digest = hashlib.sha256(post["text"].encode()).hexdigest()[:16]
                changed = bool(old_post and (old_post.get("content_hash") != digest or old_post["id"] != post["id"]))
                record = {**post, "source": name, "content_hash": digest,
                          "first_seen_at": old_post["first_seen_at"] if old_post else now,
                          "updated_at": now if not old_post or changed else old_post["updated_at"],
                          "edited": changed or bool(old_post and old_post.get("edited")),
                          "backfill": old_post.get("backfill", False) if old_post else baseline or (now_dt - parse_time(post["published_at"])).total_seconds() > config.get("alert_max_age_minutes", 60) * 60,
                          "analysis": analyze_post(post)}
                records[key] = record
                for alias in [post["id"]] + post.get("edit_ids", []):
                    aliases[alias] = key
        if state["status"] in ("error", "partial"):
            state["failures"] = old.get("failures", 0) + 1
            delay = min(360, 15 * 2 ** min(state["failures"] - 1, 5))
            state["retry_after"] = (now_dt + timedelta(minutes=delay)).isoformat()
        else:
            state["failures"] = 0
            state.pop("retry_after", None)
        statuses.append(state["status"])
        out["sources"][name] = state
    for record in records.values():
        record["analysis"] = analyze_post(record)  # Rule changes do not change first_seen_at.
    cutoff = now_dt - timedelta(days=config.get("retention_days", 90))
    out["posts"] = sorted((p for p in records.values() if parse_time(p["published_at"]) >= cutoff),
                          key=lambda p: (p["published_at"], int(p["id"])), reverse=True)[:config.get("retain_posts", 300)]
    primary = out["sources"].get("twscrape", {})
    if statuses and all(s == "disabled" for s in statuses):
        out["status"] = "disabled"
    elif statuses and all(s == "unconfigured" for s in statuses):
        out["status"] = "unconfigured"
    elif primary.get("status") == "ok" and primary.get("coverage") == "overlap":
        out["status"] = "ok"
    elif any(s in ("ok", "partial") for s in statuses):
        out["status"] = "degraded"
    else:
        out["status"] = "error"
    out["schema_version"] = 1
    out.pop("snapshot_id", None)
    out["snapshot_id"] = hashlib.sha256(json.dumps(out, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    return out


def collect(config, previous, env=None, now=None):
    env = os.environ if env is None else env
    now = now or utcnow()
    if not config.get("enabled", True):
        return [{"source": "twscrape", "status": "disabled", "code": "disabled", "posts": []}]
    results = []
    credentials = {"twscrape": env.get("CZ_X_COOKIES", ""), "rss": env.get("CZ_RSS_URL", "")}
    for name, credential in credentials.items():
        old = previous.get("sources", {}).get(name, {})
        if not credential:
            results.append({"source": name, "status": "unconfigured", "code": "unconfigured", "posts": []})
            continue
        if old.get("retry_after") and parse_time(old["retry_after"]) > parse_time(now):
            results.append({"source": name, "status": "cooldown", "code": "cooldown", "posts": []})
            continue
        if name == "twscrape":
            result = asyncio.run(fetch_twscrape(config, old, credential))
        else:
            primary = next((r for r in results if r["source"] == "twscrape"), {})
            if primary.get("status") == "ok":
                continue  # RSS is an optional fallback, not an extra load every run.
            result = fetch_rss(config, credential)
        results.append(result)
    return results


def main():
    config = json.loads((ROOT / "config.json").read_text())["cz_monitor"]
    path = ROOT / "data/cz.json"
    previous = json.loads(path.read_text()) if path.exists() else initial_snapshot(config["username"])
    # Invalid persisted state is a visible job failure, never silently reset history.
    if previous.get("schema_version") != 1:
        raise ValueError("Unsupported CZ snapshot schema")
    out = merge_snapshot(previous, collect(config, previous), config)
    atomic_json(path, out)
    print(f"CZ: status={out['status']} posts={len(out['posts'])}; no credentials in snapshot")
    return 0 if out["status"] in ("ok", "unconfigured", "disabled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
