#!/usr/bin/env python3
"""Publish only a static allowlist, never the entire checkout/session directory."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["index.html", "config.json", ".nojekyll", "scripts/ema-radar.js", "scripts/cz-radar.js",
         "styles/cz-radar.css", "data/latest.json", "data/history.json", "data/ema.json", "data/cz.json",
         "data/refresh-state.json", "research/assets.json"]


def build(root=ROOT):
    target = root / "_site"
    if target.exists():
        shutil.rmtree(target)
    for name in FILES:
        source = root / name
        if source.is_symlink():
            raise ValueError("Publish source must not be a symlink")
        if name.endswith(".json"):
            json.loads(source.read_text())
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    hashes = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in FILES}
    build_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:20]
    cz = json.loads((target / "data/cz.json").read_text())
    (target / "data/deployment.json").write_text(json.dumps({"build_id": build_id,
        "cz_snapshot_id": cz["snapshot_id"], "files": hashes}, indent=2) + "\n")
    print(f"Built static allowlist: {len(FILES)} files; build={build_id}")


if __name__ == "__main__":
    build()
