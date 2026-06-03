"""Watcher smoke test: confirm the live watcher indexes new files and removes
deleted ones. AI is off so it runs fast.

The temp dir is created inside the project (not under AppData) because the
watcher's exclusion rules skip anything beneath an AppData ancestor — which is
correct in production (the default index lives in the hidden ~/.filesearch).
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from filesearch.config import Config
from filesearch.watcher import Watcher

PROJECT = Path(__file__).resolve().parents[1]


def indexed_names(watcher: Watcher) -> list[str]:
    return [Path(p).name for p in watcher.indexer.index.all_paths()]


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="fs_watch_", dir=str(PROJECT)))
    root = base / "docs"
    root.mkdir()
    cfg = Config(
        scan_roots=[str(root)],
        db_path=str(base / "index.db"),  # db OUTSIDE the watched root
        enable_ai_tagging=False,
        enable_embeddings=False,
    )
    watcher = Watcher(cfg, debounce=0.4)
    watched = watcher.start()
    print(f"watching {watched} location(s); waiting for observer to settle…")
    time.sleep(1.0)

    failures = []

    # 1. Create a file -> should be indexed.
    f = root / "hello.txt"
    f.write_text("a quick note about the quarterly budget", encoding="utf-8")
    time.sleep(2.0)
    if "hello.txt" in indexed_names(watcher):
        print("  create -> indexed: OK")
    else:
        print(f"  create -> NOT indexed. index={indexed_names(watcher)}")
        failures.append("create")

    # 2. Modify the file -> should remain indexed (and re-processed).
    f.write_text("updated note about budget and hiring plans", encoding="utf-8")
    time.sleep(2.0)
    if "hello.txt" in indexed_names(watcher):
        print("  modify -> still indexed: OK")
    else:
        failures.append("modify")

    # 3. Delete the file -> should be removed from the index.
    f.unlink()
    time.sleep(2.0)
    if "hello.txt" not in indexed_names(watcher):
        print("  delete -> removed: OK")
    else:
        print(f"  delete -> still present. index={indexed_names(watcher)}")
        failures.append("delete")

    watcher.stop()
    import shutil

    shutil.rmtree(base, ignore_errors=True)

    if failures:
        print(f"\nWATCH SMOKE TEST FAILED: {failures}")
        return 1
    print("\nWATCH SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
