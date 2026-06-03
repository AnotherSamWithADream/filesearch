"""FastAPI app: JSON search API + the static single-page UI.

The same app powers both ``filesearch serve`` (open in a browser) and
``filesearch gui`` (loaded in a native desktop window). All routes are local;
``/api/open`` only opens paths that exist in the index.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import Config
from ..db import Index
from ..search import SearchEngine

STATIC_DIR = Path(__file__).parent / "static"


class OpenRequest(BaseModel):
    path: str
    reveal: bool = False  # True -> reveal in file manager instead of opening


def _open_path(path: str, reveal: bool) -> None:
    if sys.platform.startswith("win"):
        if reveal:
            subprocess.run(["explorer", f"/select,{path}"], check=False)
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open"] + (["-R", path] if reveal else [path]), check=False)
    else:
        target = str(Path(path).parent) if reveal else path
        subprocess.run(["xdg-open", target], check=False)


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="filesearch", version="0.1.0")
    engine = SearchEngine(cfg)
    index = engine.index

    @app.get("/api/status")
    def status() -> dict:
        return {
            "stats": index.stats(),
            "models": {
                "text": cfg.text_model,
                "vision": cfg.vision_model,
                "embed": cfg.embed_model,
            },
            "semantic_available": engine.semantic_available(),
            "scan_roots": cfg.scan_roots,
        }

    @app.get("/api/search")
    def search(
        q: str = Query(..., min_length=1),
        mode: str = Query("hybrid", pattern="^(hybrid|keyword|semantic)$"),
        limit: int = Query(20, ge=1, le=200),
        ext: str | None = None,
        category: str | None = None,
    ) -> dict:
        filters: dict = {}
        if ext:
            filters["ext"] = [e.strip() for e in ext.split(",") if e.strip()]
        if category:
            filters["category"] = category
        hits = engine.search(q, limit=limit, mode=mode, filters=filters or None)
        return {
            "query": q,
            "mode": mode,
            "count": len(hits),
            "hits": [h.model_dump() for h in hits],
        }

    @app.post("/api/open")
    def open_file(req: OpenRequest) -> JSONResponse:
        if not index.has_path(req.path):
            raise HTTPException(status_code=404, detail="Path not in index")
        if not Path(req.path).exists():
            raise HTTPException(status_code=410, detail="File no longer exists")
        try:
            _open_path(req.path, req.reveal)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))
        return JSONResponse({"ok": True})

    # Serve the SPA at the root (registered after the API routes).
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app
