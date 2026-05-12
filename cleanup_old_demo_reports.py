from __future__ import annotations

import json
from pathlib import Path

from av_common import BASE_DIR, is_legacy_bundled_demo

folders = [BASE_DIR / "reports_outbox", BASE_DIR / "reports_inbox"]
removed = 0

for folder in folders:
    folder.mkdir(exist_ok=True)
    for path in folder.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if is_legacy_bundled_demo(payload):
            path.unlink()
            removed += 1
            print(f"Deleted legacy demo report: {path.name}")

print(f"Done. Removed {removed} legacy demo report(s).")
