#!/usr/bin/env python3
"""Fail deployment verification if the live site still serves a previous snapshot."""
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def verify(url, site=Path("_site"), attempts=8):
    if urlsplit(url).scheme != "https":
        raise ValueError("Expected HTTPS Pages URL")
    expected = json.loads((site / "data/deployment.json").read_text())
    for attempt in range(attempts):
        try:
            for name in ("data/deployment.json", "data/cz.json", "index.html", "scripts/cz-radar.js"):
                request = urllib.request.Request(url.rstrip("/") + "/" + name + f"?verify={expected['build_id']}-{attempt}",
                                                 headers={"Cache-Control": "no-cache"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = response.read()
                if name == "data/deployment.json":
                    if json.loads(body)["build_id"] != expected["build_id"]:
                        raise ValueError("Old manifest")
                elif hashlib.sha256(body).hexdigest() != expected["files"][name]:
                    raise ValueError("Old content")
            print("Verified live Pages build and CZ snapshot.")
            return
        except Exception:
            if attempt + 1 < attempts:
                time.sleep(10)
    raise RuntimeError("Live site did not match this deployment; inspect Pages and CDN status")


if __name__ == "__main__":
    verify(sys.argv[1])
