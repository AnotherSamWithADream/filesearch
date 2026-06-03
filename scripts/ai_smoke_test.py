"""AI-path smoke test: real Ollama tagging + semantic search.

Indexes a few text files with AI tagging ON, prints the model-generated
tags/summary per file, then runs *semantic* queries whose wording does NOT
overlap the files' keywords — so a hit proves embeddings (not FTS) are working.

Uses already-pulled models by default so it needs no large download:
    text  = qwen2.5:7b-instruct   embed = nomic-embed-text
Override via argv: python scripts/ai_smoke_test.py <text_model> <embed_model>
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Avoid cp1252 console crashes when printing model output on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from filesearch.config import Config
from filesearch.indexer import Indexer
from filesearch.search import SearchEngine

TEXT_MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b-instruct"
EMBED_MODEL = sys.argv[2] if len(sys.argv) > 2 else "nomic-embed-text"

FILES = {
    "budget_notes.txt": "Q3 budget planning. We need to cut marketing spend by 15% and reallocate the savings to the engineering team.",
    "invoice_acme.txt": "Invoice #4471. Acme Corp owes $1,200 for consulting services rendered in March. Payment is due within 30 days.",
    "recipe.md": "# Banana Bread\nIngredients: flour, ripe bananas, sugar, eggs, butter. Bake at 350F for 60 minutes until golden.",
    "vacation.txt": "Trip itinerary: Tokyo, Kyoto, and Osaka. Visit ancient temples, ride the bullet train, and try authentic ramen.",
    "bugfix.py": "def fix_login():\n    # patch the authentication timeout that logged users out too early\n    session.timeout = 3600\n",
}

# Semantic queries -> expected file (wording deliberately avoids the file's words).
SEMANTIC = {
    "money a client owes our company": "invoice_acme.txt",
    "how to reduce business expenses": "budget_notes.txt",
    "places to travel in east asia": "vacation.txt",
    "sign-in security problem": "bugfix.py",
    "baking dessert instructions": "recipe.md",
}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="filesearch_ai_"))
    root = tmp / "docs"
    root.mkdir()
    for name, body in FILES.items():
        (root / name).write_text(body, encoding="utf-8")

    cfg = Config(
        scan_roots=[str(root)],
        db_path=str(tmp / "index.db"),
        text_model=TEXT_MODEL,
        embed_model=EMBED_MODEL,
        enable_ai_tagging=True,
        enable_embeddings=True,
        index_images=False,
        max_workers=2,
    )
    indexer = Indexer(cfg)
    caps = indexer.capabilities()
    print(f"capabilities: {caps}\n")
    if not caps["text"]:
        print(f"FAIL: text model '{TEXT_MODEL}' not available in Ollama.")
        return 1

    print(f"Indexing {len(FILES)} files with {TEXT_MODEL} (+ {EMBED_MODEL} embeddings)…")
    stats = indexer.run_scan()
    print(f"  scanned={stats['scanned']} ai_tagged={stats['reindexed']} embedded(stats)\n")

    # Show the AI-generated tags/summary per file.
    rows = indexer.index.conn.execute(
        "SELECT name, ai_tagged, category, tags, summary FROM files ORDER BY name"
    ).fetchall()
    print("AI tags per file:")
    for r in rows:
        print(f"  • {r['name']}  [{r['category']}]  ai_tagged={r['ai_tagged']}")
        print(f"      tags: {r['tags']}")
        print(f"      summary: {r['summary'][:120]}")
    tagged = sum(1 for r in rows if r["ai_tagged"])
    embedded = indexer.index.stats()["embedded"]
    print(f"\n  {tagged}/{len(rows)} AI-tagged, {embedded} embedded\n")

    engine = SearchEngine(cfg)
    print("Semantic search (query wording avoids file keywords):")
    passes = 0
    for q, expected in SEMANTIC.items():
        hits = engine.search(q, mode="semantic", limit=3)
        names = [h.name for h in hits]
        top_ok = bool(names) and names[0] == expected
        in_top = expected in names
        status = "OK(top)" if top_ok else ("OK(in top3)" if in_top else "MISS")
        if in_top:
            passes += 1
        print(f"  '{q}'\n     -> {status}: {names}")

    indexer.index.close()
    engine.index.close()
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nsemantic: {passes}/{len(SEMANTIC)} expected files in top-3")
    ok = tagged == len(rows) and embedded == len(rows) and passes >= len(SEMANTIC) - 1
    print("AI SMOKE TEST PASSED" if ok else "AI SMOKE TEST: review output above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
