"""SQLite index: a ``files`` table, an FTS5 full-text mirror kept in sync by
triggers, and an ``embeddings`` table for semantic (vector) search.

The connection is shared across threads (the indexer fans work out to a pool)
and guarded by a re-entrant lock, so all access goes through this class.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from .models import FileMeta, TagResult

# FTS column order — used by snippet() column indexing below.
#   0=name 1=path 2=summary 3=tags 4=entities 5=content
_CONTENT_COL = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    ext         TEXT,
    mime        TEXT,
    size        INTEGER,
    mtime       REAL,
    summary     TEXT DEFAULT '',
    category    TEXT DEFAULT '',
    language    TEXT DEFAULT '',
    tags        TEXT DEFAULT '',
    entities    TEXT DEFAULT '',
    content     TEXT DEFAULT '',
    indexed_at  REAL,
    ai_tagged   INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    name, path, summary, tags, entities, content,
    content='files', content_rowid='id', tokenize='unicode61'
);

-- Keep the FTS index in sync with the files table.
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, name, path, summary, tags, entities, content)
    VALUES (new.id, new.name, new.path, new.summary, new.tags, new.entities, new.content);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, path, summary, tags, entities, content)
    VALUES ('delete', old.id, old.name, old.path, old.summary, old.tags, old.entities, old.content);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, path, summary, tags, entities, content)
    VALUES ('delete', old.id, old.name, old.path, old.summary, old.tags, old.entities, old.content);
    INSERT INTO files_fts(rowid, name, path, summary, tags, entities, content)
    VALUES (new.id, new.name, new.path, new.summary, new.tags, new.entities, new.content);
END;

CREATE TABLE IF NOT EXISTS embeddings (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    dim     INTEGER,
    vector  BLOB
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _fts_match_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression (prefix AND of terms)."""
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    if not tokens:
        return None
    # Quote each token (handles unicode/digits safely) and prefix-match it.
    return " ".join(f'"{t}"*' for t in tokens)


def _tags_to_str(tags: list[str]) -> str:
    return ", ".join(tags)


def tags_from_str(s: str | None) -> list[str]:
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


class Index:
    def __init__(self, db_path: str | Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # --- incremental bookkeeping -------------------------------------------
    def needs_reindex(self, path: str, mtime: float, size: int) -> bool:
        """True if the file is new or changed since last index (mtime/size)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT mtime, size FROM files WHERE path = ?", (path,)
            ).fetchone()
        if row is None:
            return True
        return abs(row["mtime"] - mtime) > 1e-3 or row["size"] != size

    def all_paths(self) -> set[str]:
        with self._lock:
            rows = self.conn.execute("SELECT path FROM files").fetchall()
        return {r["path"] for r in rows}

    def has_path(self, path: str) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM files WHERE path = ? LIMIT 1", (path,)
            ).fetchone()
        return row is not None

    # --- writes ------------------------------------------------------------
    def upsert_file(
        self,
        meta: FileMeta,
        content: str,
        tag: TagResult,
        ai_tagged: bool,
    ) -> int:
        params = {
            "path": meta.path,
            "name": meta.name,
            "ext": meta.ext,
            "mime": meta.mime,
            "size": meta.size,
            "mtime": meta.mtime,
            "summary": tag.summary,
            "category": tag.category,
            "language": tag.language,
            "tags": _tags_to_str(tag.tags),
            "entities": _tags_to_str(tag.entities),
            "content": content,
            "indexed_at": time.time(),
            "ai_tagged": 1 if ai_tagged else 0,
        }
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO files
                    (path, name, ext, mime, size, mtime, summary, category,
                     language, tags, entities, content, indexed_at, ai_tagged)
                VALUES
                    (:path, :name, :ext, :mime, :size, :mtime, :summary, :category,
                     :language, :tags, :entities, :content, :indexed_at, :ai_tagged)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name, ext=excluded.ext, mime=excluded.mime,
                    size=excluded.size, mtime=excluded.mtime, summary=excluded.summary,
                    category=excluded.category, language=excluded.language,
                    tags=excluded.tags, entities=excluded.entities,
                    content=excluded.content, indexed_at=excluded.indexed_at,
                    ai_tagged=excluded.ai_tagged
                """,
                params,
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT id FROM files WHERE path = ?", (meta.path,)
            ).fetchone()
        return int(row["id"])

    def set_embedding(self, file_id: int, vector: np.ndarray) -> None:
        v = np.asarray(vector, dtype=np.float32).ravel()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO embeddings(file_id, dim, vector) VALUES(?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET dim=excluded.dim, vector=excluded.vector
                """,
                (file_id, int(v.shape[0]), v.tobytes()),
            )
            self.conn.commit()

    def delete_by_path(self, path: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
            self.conn.commit()

    def delete_under(self, prefix: str) -> int:
        """Delete the file at ``prefix`` and everything beneath it (dir delete)."""
        import os as _os

        pref = _os.path.normcase(_os.path.abspath(prefix))
        with self._lock:
            rows = self.conn.execute("SELECT path FROM files").fetchall()
            victims = [
                r["path"]
                for r in rows
                if (rp := _os.path.normcase(_os.path.abspath(r["path"]))) == pref
                or rp.startswith(pref + _os.sep)
            ]
            for v in victims:
                self.conn.execute("DELETE FROM files WHERE path = ?", (v,))
            self.conn.commit()
        return len(victims)

    # --- search ------------------------------------------------------------
    def keyword_search(
        self, query: str, limit: int, filters: dict | None = None
    ) -> list[sqlite3.Row]:
        match = _fts_match_query(query)
        if not match:
            return []
        where, args = ["files_fts MATCH ?"], [match]
        self._apply_filters(where, args, filters, alias="f")
        sql = f"""
            SELECT f.*, bm25(files_fts) AS bm25,
                   snippet(files_fts, {_CONTENT_COL}, '[[', ']]', ' … ', 14) AS snip
            FROM files_fts JOIN files f ON f.id = files_fts.rowid
            WHERE {' AND '.join(where)}
            ORDER BY bm25
            LIMIT ?
        """
        args.append(limit)
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def load_embeddings(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (ids[N], matrix[N, dim]) of all stored embeddings."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_id, dim, vector FROM embeddings"
            ).fetchall()
        if not rows:
            return np.empty((0,), dtype=np.int64), np.empty((0, 0), dtype=np.float32)
        ids = np.fromiter((r["file_id"] for r in rows), dtype=np.int64, count=len(rows))
        dim = rows[0]["dim"]
        mat = np.zeros((len(rows), dim), dtype=np.float32)
        for i, r in enumerate(rows):
            vec = np.frombuffer(r["vector"], dtype=np.float32)
            if vec.shape[0] == dim:
                mat[i] = vec
        return ids, mat

    def files_by_ids(self, ids: list[int], filters: dict | None = None) -> dict[int, sqlite3.Row]:
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        where = [f"f.id IN ({placeholders})"]
        args: list = list(ids)
        self._apply_filters(where, args, filters, alias="f")
        sql = f"SELECT f.* FROM files f WHERE {' AND '.join(where)}"
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return {int(r["id"]): r for r in rows}

    @staticmethod
    def _apply_filters(where: list[str], args: list, filters: dict | None, alias: str) -> None:
        if not filters:
            return
        if filters.get("ext"):
            exts = filters["ext"]
            if isinstance(exts, str):
                exts = [exts]
            exts = [e.lower().lstrip(".") for e in exts]
            ph = ",".join("?" for _ in exts)
            # Stored ext keeps its leading dot (".py"); strip it both sides.
            where.append(f"ltrim(lower({alias}.ext), '.') IN ({ph})")
            args.extend(exts)
        if filters.get("category"):
            where.append(f"lower({alias}.category) = ?")
            args.append(str(filters["category"]).lower())
        if filters.get("since") is not None:
            where.append(f"{alias}.mtime >= ?")
            args.append(float(filters["since"]))
        if filters.get("until") is not None:
            where.append(f"{alias}.mtime <= ?")
            args.append(float(filters["until"]))
        if filters.get("min_size") is not None:
            where.append(f"{alias}.size >= ?")
            args.append(int(filters["min_size"]))
        if filters.get("max_size") is not None:
            where.append(f"{alias}.size <= ?")
            args.append(int(filters["max_size"]))

    # --- stats / meta ------------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
            tagged = self.conn.execute(
                "SELECT COUNT(*) AS c FROM files WHERE ai_tagged = 1"
            ).fetchone()["c"]
            embedded = self.conn.execute(
                "SELECT COUNT(*) AS c FROM embeddings"
            ).fetchone()["c"]
            size = self.conn.execute(
                "SELECT COALESCE(SUM(size), 0) AS s FROM files"
            ).fetchone()["s"]
            last = self.conn.execute(
                "SELECT MAX(indexed_at) AS m FROM files"
            ).fetchone()["m"]
        return {
            "files": total,
            "ai_tagged": tagged,
            "embedded": embedded,
            "total_size": size,
            "last_indexed": last,
        }

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self.conn.commit()
