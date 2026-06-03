"""Indexing orchestration: scan -> extract -> AI tag -> embed -> store.

The model capabilities (which models are actually pulled) are probed once per
scan so we don't re-list Ollama models for every file. Work is fanned out to a
bounded thread pool; DB writes are serialized inside :class:`Index`.
"""

from __future__ import annotations

import mimetypes
import os
import stat
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from . import extract, scanner
from .config import Config
from .db import Index
from .models import FileMeta, TagResult
from .ollama_client import OllamaClient

ProgressFn = Callable[[dict], None]


class Indexer:
    def __init__(
        self,
        cfg: Config,
        index: Index | None = None,
        client: OllamaClient | None = None,
    ):
        self.cfg = cfg
        self.index = index or Index(cfg.db_path)
        self.client = client or OllamaClient(cfg.ollama_host)
        self._caps_cache: dict | None = None
        self._caps_at: float = 0.0

    # --- capability probing ------------------------------------------------
    def capabilities(self) -> dict:
        up = self.cfg.enable_ai_tagging and self.client.ping()
        names: set[str] = set()
        if up:
            try:
                names = set(self.client.list_model_names())
            except Exception:
                up = False

        def have(model: str | None) -> bool:
            if not model:
                return False
            base = model.split(":")[0]
            return any(n == model or n.split(":")[0] == base for n in names)

        return {
            "ai": up,
            "text": up and have(self.cfg.text_model),
            "vision": up and self.cfg.index_images and have(self.cfg.vision_model),
            "embed": up and self.cfg.enable_embeddings and have(self.cfg.embed_model),
            "model_names": names,
        }

    def _cached_caps(self, ttl: float = 60.0) -> dict:
        now = time.time()
        if self._caps_cache is None or now - self._caps_at > ttl:
            self._caps_cache = self.capabilities()
            self._caps_at = now
        return self._caps_cache

    # --- per-file ----------------------------------------------------------
    def _embed_text(self, meta: FileMeta, tag: TagResult, content: str) -> str:
        parts = [meta.name]
        if tag.summary:
            parts.append(tag.summary)
        if tag.tags:
            parts.append(" ".join(tag.tags))
        if tag.entities:
            parts.append(" ".join(tag.entities))
        if content:
            parts.append(content[:800])
        return "\n".join(p for p in parts if p).strip()[:2000]

    def index_file(self, meta: FileMeta, caps: dict) -> dict:
        content = ""
        kind = "none"
        if meta.size <= self.cfg.max_file_bytes:
            ex = extract.extract(
                meta.path, meta.ext, self.cfg.content_char_cap, self.cfg.index_images
            )
            kind, content = ex.kind, ex.content

        tag = TagResult()
        ai_tagged = False
        try:
            if kind == "text" and len(content.strip()) >= 20 and caps["text"]:
                tag = self.client.tag_text(meta.name, content, self.cfg.text_model)
                ai_tagged = True
            elif kind == "image" and caps["vision"]:
                tag = self.client.tag_image(meta.path, self.cfg.vision_model)
                ai_tagged = True
        except Exception:
            ai_tagged = False

        file_id = self.index.upsert_file(meta, content, tag, ai_tagged)

        if caps["embed"]:
            etext = self._embed_text(meta, tag, content)
            if etext:
                vec = self.client.embed(etext, self.cfg.embed_model)
                if vec is not None:
                    self.index.set_embedding(file_id, vec)

        return {"path": meta.path, "ai_tagged": ai_tagged, "kind": kind, "ok": True}

    def index_path(self, path: str) -> dict | None:
        """Index a single path on demand (used by the watcher)."""
        if scanner.is_excluded_path(path, self.cfg):
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        if not stat.S_ISREG(st.st_mode):
            return None
        meta = FileMeta(
            path=path,
            name=os.path.basename(path),
            ext=os.path.splitext(path)[1].lower(),
            size=st.st_size,
            mtime=st.st_mtime,
            mime=mimetypes.guess_type(path)[0],
        )
        if not self.index.needs_reindex(path, meta.mtime, meta.size):
            return {"path": path, "skipped": True, "ok": True}
        return self.index_file(meta, self._cached_caps())

    # --- full scan ---------------------------------------------------------
    def run_scan(
        self, on_progress: ProgressFn | None = None, limit: int | None = None
    ) -> dict:
        caps = self.capabilities()
        seen: set[str] = set()
        stats = {"scanned": 0, "indexed": 0, "reindexed": 0, "skipped": 0, "errors": 0, "caps": caps}
        max_inflight = max(self.cfg.max_workers * 4, 8)

        def collect(fut) -> None:
            try:
                res = fut.result()
                if res and res.get("ok") and not res.get("skipped"):
                    stats["indexed"] += 1
                if res and res.get("ai_tagged"):
                    stats["reindexed"] += 1
                if on_progress and res:
                    on_progress(res)
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                if on_progress:
                    on_progress({"error": str(e), "ok": False})

        submitted = 0
        with ThreadPoolExecutor(max_workers=self.cfg.max_workers) as pool:
            pending: set = set()
            for meta in scanner.iter_files(self.cfg):
                seen.add(os.path.normcase(meta.path))
                stats["scanned"] += 1
                if on_progress:
                    on_progress({"scanning": meta.path, "scanned": stats["scanned"]})

                if not self.index.needs_reindex(meta.path, meta.mtime, meta.size):
                    stats["skipped"] += 1
                    continue

                pending.add(pool.submit(self.index_file, meta, caps))
                submitted += 1
                if len(pending) >= max_inflight:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for f in done:
                        collect(f)

                if limit and submitted >= limit:
                    break

            for f in pending:
                collect(f)

        # Prune files that disappeared from disk (only on a full, unlimited scan).
        if not limit:
            stats["pruned"] = 0
            roots = [Path(r) for r in self.cfg.scan_roots]
            for p in self.index.all_paths():
                if os.path.normcase(p) in seen:
                    continue
                if any(scanner._within(Path(p), r) for r in roots):
                    self.index.delete_by_path(p)
                    stats["pruned"] += 1

        self.index.set_meta("last_scan", str(time.time()))
        return stats
