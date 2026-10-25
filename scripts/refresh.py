#!/usr/bin/env python3
"""One writer for all snapshots. Missed schedules catch up on the next run."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from compute_cz import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def due_slot(task, now):
    if task == "market":
        slot = (now - timedelta(days=now.weekday())).replace(hour=1, minute=0, second=0, microsecond=0)
        return slot if slot <= now else slot - timedelta(days=7)
    slot = now.replace(hour=1, minute=15, second=0, microsecond=0)
    return slot if slot <= now else slot - timedelta(days=1)


def due(task, state, now):
    if task == "cz":
        return True
    if state.get("slot") == due_slot(task, now).isoformat():
        return False
    last = state.get("last_attempt_at")
    return not last or (now - datetime.fromisoformat(last)).total_seconds() >= 3600


def run_task(task):
    script, paths, timeout = {
        "market": ("compute.py", ["latest.json", "history.json"], 240),
        "ema": ("compute_ema.py", ["ema.json"], 240),
        "cz": ("compute_cz.py", ["cz.json"], 150),
    }[task]
    backups = {p: (ROOT / "data" / p).read_bytes() if (ROOT / "data" / p).exists() else None for p in paths}
    try:
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT,
                                timeout=timeout, capture_output=True, text=True)
        data = json.loads((ROOT / "data" / paths[0]).read_text())
        if task == "cz":
            # Valid degraded snapshots still need to be published. An exception before
            # writing must not be mistaken for a current successful check.
            changed = (ROOT / "data" / paths[0]).read_bytes() != backups[paths[0]]
            if not changed and result.returncode:
                raise ValueError("No new snapshot")
            status = data["status"]
            return status if status in ("ok", "unconfigured", "disabled") else "degraded"
        if result.returncode != 0 and task == "market":
            raise ValueError("Collector failed")
        if task == "market" and backups["latest.json"]:
            previous = json.loads(backups["latest.json"])
            for group in ("assets", "bench"):
                data[group] = {**previous.get(group, {}), **data.get(group, {})}
            atomic_json(ROOT / "data/latest.json", data)
        return "degraded" if data.get("errors") or result.returncode else "ok"
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
        for name, backup in backups.items():
            if backup is not None:
                (ROOT / "data" / name).write_bytes(backup)
        return "error"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=["auto", "all", "cz", "market", "ema", "publish"], default="auto")
    scope = parser.parse_args().scope
    if scope == "publish":
        return
    path = ROOT / "data/refresh-state.json"
    state = json.loads(path.read_text()) if path.exists() else {"tasks": {}}
    now = datetime.now(timezone.utc)
    for task in ("cz", "market", "ema"):
        old = state["tasks"].get(task, {})
        if scope not in ("all", task) and (scope != "auto" or not due(task, old, now)):
            continue
        status = run_task(task)
        state["tasks"][task] = {**old, "last_attempt_at": now.isoformat(), "status": status}
        if status == "ok":
            state["tasks"][task]["last_success_at"] = now.isoformat()
            if task != "cz":
                state["tasks"][task]["slot"] = due_slot(task, now).isoformat()
        print(f"{task}: {status}")
        atomic_json(path, state)


if __name__ == "__main__":
    main()
