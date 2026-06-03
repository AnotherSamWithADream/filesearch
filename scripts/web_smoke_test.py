"""Web API smoke test using FastAPI's in-process TestClient (no server/port)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from filesearch.config import Config
from filesearch.indexer import Indexer
from filesearch.web.server import create_app


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="filesearch_web_"))
    root = tmp / "docs"
    root.mkdir()
    (root / "budget.txt").write_text("Q3 budget and marketing plan.", encoding="utf-8")
    (root / "app.py").write_text("def calculate_tax(x): return x*0.2", encoding="utf-8")

    cfg = Config(
        scan_roots=[str(root)],
        db_path=str(tmp / "index.db"),
        enable_ai_tagging=False,
        enable_embeddings=False,
    )
    Indexer(cfg).run_scan()

    client = TestClient(create_app(cfg))
    failures = []

    r = client.get("/api/status")
    print("GET /api/status ->", r.status_code, r.json()["stats"])
    if r.status_code != 200 or r.json()["stats"]["files"] != 2:
        failures.append("status")

    r = client.get("/api/search", params={"q": "budget", "mode": "keyword"})
    js = r.json()
    names = [h["name"] for h in js["hits"]]
    print("GET /api/search?q=budget ->", r.status_code, names)
    if r.status_code != 200 or "budget.txt" not in names:
        failures.append("search")

    r = client.get("/api/search", params={"q": "tax", "ext": "py"})
    names = [h["name"] for h in r.json()["hits"]]
    print("GET /api/search?q=tax&ext=py ->", names)
    if "app.py" not in names:
        failures.append("filtered-search")

    r = client.get("/")
    print("GET / ->", r.status_code, "(serves index.html)" if "<title>filesearch" in r.text else "(NO UI)")
    if r.status_code != 200 or "<title>filesearch" not in r.text:
        failures.append("static-ui")

    r = client.post("/api/open", json={"path": "C:/definitely/not/indexed.txt"})
    print("POST /api/open (bad path) ->", r.status_code, "(rejects unknown path)")
    if r.status_code != 404:
        failures.append("open-guard")

    import shutil

    shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"\nWEB SMOKE TEST FAILED: {failures}")
        return 1
    print("\nWEB SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
