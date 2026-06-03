"""Hybrid search: FTS5 keyword search + semantic vector search, fused.

Three modes:￼
  * ``keyword``  — FTS5 BM25 over name/path/summary/tags/entities/content
  * ``semantic`` — cosine similarity over stored embeddings (needs embed model)
  * ``hybrid``   — both, merged with Reciprocal Rank Fusion (default)

RRF is used for the merge so the two very different score scales (BM25 vs
cosine) never need to be normalized against each other.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from .config import Config
from .db import Index, tags_from_str
from .models import SearchHit
from .ollama_client import OllamaClient

_RRF_K = 60


class SearchEngine:
    def __init__(
        self,
        cfg: Config,
        index: Index | None = None,
        client: OllamaClient | None = None,
    ):
        self.cfg = cfg
        self.index = index or Index(cfg.db_path)
        self.client = client or OllamaClient(cfg.ollama_host)

    # --- public ------------------------------------------------------------
    def search(
        self,
        query: str,
        limit: int = 20,
        mode: str = "hybrid",
        filters: dict | None = None,
    ) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []

        if mode == "keyword":
            hits = self._keyword_hits(query, limit, filters)
        elif mode == "semantic":
            hits = self._semantic_hits(query, limit, filters)
        else:
            hits = self._hybrid_hits(query, limit, filters)

        # Normalize display scores to 0..1 within this result set.
        if hits:
            top = max(h.score for h in hits) or 1.0
            for h in hits:
                h.score = round(h.score / top, 4)
        return hits[:limit]

    def semantic_available(self) -> bool:
        return bool(self.cfg.enable_embeddings and self.cfg.embed_model)

    # --- keyword -----------------------------------------------------------
    def _keyword_rows(self, query: str, k: int, filters: dict | None) -> list[sqlite3.Row]:
        return self.index.keyword_search(query, k, filters)

    def _keyword_hits(self, query: str, limit: int, filters: dict | None) -> list[SearchHit]:
        rows = self._keyword_rows(query, limit, filters)
        hits = []
        for row in rows:
            # bm25: lower is better -> use negative as a higher-is-better score.
            score = -float(row["bm25"])
            hits.append(_row_to_hit(row, score, "keyword", row["snip"]))
        return hits

    # --- semantic ----------------------------------------------------------
    def _semantic_ranked(
        self, query: str, k: int, filters: dict | None
    ) -> list[tuple[int, sqlite3.Row, float]]:
        if not self.semantic_available():
            return []
        qv = self.client.embed(query, self.cfg.embed_model)
        if qv is None:
            return []
        ids, mat = self.index.load_embeddings()
        if ids.size == 0 or mat.size == 0:
            return []
        if mat.shape[1] != qv.shape[0]:
            # Embedding model changed since indexing — dimensions don't match.
            return []
        qn = qv / (np.linalg.norm(qv) + 1e-8)
        norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8
        sims = (mat / norms) @ qn
        # Take a generous candidate pool, then apply filters via a single fetch.
        pool = max(limit_pool(k), 1)
        order = np.argsort(-sims)[:pool]
        cand_ids = [int(ids[i]) for i in order]
        rows = self.index.files_by_ids(cand_ids, filters)
        ranked: list[tuple[int, sqlite3.Row, float]] = []
        for i in order:
            fid = int(ids[i])
            row = rows.get(fid)
            if row is not None:
                ranked.append((fid, row, float(sims[i])))
            if len(ranked) >= k:
                break
        return ranked

    def _semantic_hits(self, query: str, limit: int, filters: dict | None) -> list[SearchHit]:
        ranked = self._semantic_ranked(query, limit, filters)
        return [_row_to_hit(row, cos, "semantic") for _fid, row, cos in ranked]

    # --- hybrid (RRF) ------------------------------------------------------
    def _hybrid_hits(self, query: str, limit: int, filters: dict | None) -> list[SearchHit]:
        kw_rows = self._keyword_rows(query, limit * 3, filters)
        sem = self._semantic_ranked(query, limit * 3, filters)

        scores: dict[int, float] = {}
        rowmap: dict[int, sqlite3.Row] = {}
        snipmap: dict[int, str] = {}
        types: dict[int, set[str]] = {}

        for rank, row in enumerate(kw_rows):
            fid = int(row["id"])
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            rowmap.setdefault(fid, row)
            snipmap.setdefault(fid, row["snip"])
            types.setdefault(fid, set()).add("keyword")

        for rank, (fid, row, _cos) in enumerate(sem):
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            rowmap.setdefault(fid, row)
            types.setdefault(fid, set()).add("semantic")

        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        hits: list[SearchHit] = []
        for fid, score in ordered[:limit]:
            t = types[fid]
            match_type = "hybrid" if len(t) > 1 else next(iter(t))
            hits.append(_row_to_hit(rowmap[fid], score, match_type, snipmap.get(fid)))
        return hits


def limit_pool(k: int) -> int:
    """Candidate pool size for semantic filtering before truncating to k."""
    return max(k * 5, 200)


def _row_to_hit(
    row: sqlite3.Row, score: float, match_type: str, snippet: str | None = None
) -> SearchHit:
    content = row["content"] if "content" in row.keys() else ""
    snip = snippet or (row["summary"] or (content[:160] if content else ""))
    return SearchHit(
        path=row["path"],
        name=row["name"],
        ext=row["ext"] or "",
        size=row["size"] or 0,
        mtime=row["mtime"] or 0.0,
        score=score,
        match_type=match_type,
        summary=row["summary"] or "",
        tags=tags_from_str(row["tags"]),
        category=row["category"] or "",
        snippet=snip or "",
    )
