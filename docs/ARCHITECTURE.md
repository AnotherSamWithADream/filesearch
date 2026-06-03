# Architecture

This document describes how filesearch is put together: the modules, the data
flow, the storage schema, and the search algorithm. For usage, see the
[README](../README.md).

## Design goals

- **Local-first & private** — the only external calls are to a local Ollama
  server and one-time model/`npm` downloads.
- **One core, many faces** — the CLI, web UI, and desktop app are thin shells
  over a shared engine (config + index + indexer + search).
- **Resilient indexing** — a single unreadable file or a flaky model response
  must never abort a scan; readers and AI calls degrade to best-effort.
- **Incremental** — re-scans only touch new/changed files.

## Module map

```
filesearch/
├── config.py          Config model + load/save (~/.filesearch/config.json), defaults, excludes
├── models.py          Pydantic schemas: FileMeta, TagResult (lenient), SearchHit
├── scanner.py         iter_files() walk + exclusion rules; is_excluded_path() for the watcher
├── extract.py         Per-type content extraction → Extracted(kind, content)
├── ollama_client.py   Ollama wrapper: tag_text, tag_image, embed, pull, ping, has_model
├── llm_checker.py     Runs/parses `llm-checker recommend`; maps categories → text/vision models
├── db.py              SQLite index: files table, FTS5 mirror (+triggers), embeddings, meta
├── indexer.py         Orchestration: scan → extract → tag → embed → store; capability probe
├── search.py          SearchEngine: keyword / semantic / hybrid (RRF) + score normalization
├── watcher.py         watchdog observer → debounced queue → incremental re-index
├── cli.py             Typer CLI: setup, scan, watch, query, status, serve, gui
├── desktop.py         Runs the web app in a thread; opens it in a pywebview window
└── web/
    ├── server.py      FastAPI app: /api/status, /api/search, /api/open + static mount
    └── static/
        └── index.html Single-page search UI (vanilla JS)
```

## Data flow

### Indexing (`scan` / `watch`)

```
scanner.iter_files(cfg)            # walk roots, apply exclusions → FileMeta
        │
        ▼  (only if size+mtime changed vs. the index)
indexer.index_file(meta, caps)
        │
        ├─▶ extract.extract()      # text? image? none?  → content string
        ├─▶ ollama_client.tag_text / tag_image   (if AI enabled & model present)
        ├─▶ db.upsert_file()       # INSERT … ON CONFLICT(path) DO UPDATE
        │        └─ triggers keep files_fts in sync
        └─▶ ollama_client.embed() → db.set_embedding()   (if embeddings enabled)
```

A full `scan` fans `index_file` out over a `ThreadPoolExecutor`, keeps a bounded
set of in-flight futures (back-pressure), then prunes index rows whose paths no
longer exist on disk. Model **capabilities** (which models are actually pulled)
are probed once per scan, not per file.

### Searching (`query` / web API)

```
SearchEngine.search(q, mode, filters)
        │
        ├─ keyword:  db.keyword_search()      # FTS5 MATCH, BM25 order, snippet()
        ├─ semantic: ollama_client.embed(q) → cosine over db.load_embeddings()
        └─ hybrid:   both lists fused with Reciprocal Rank Fusion (k=60)
        ▼
   normalize display scores to 0..1 → List[SearchHit]
```

## Storage schema (SQLite)

The connection is shared across threads (`check_same_thread=False`) and guarded
by a re-entrant lock. PRAGMAs: `journal_mode=WAL`, `synchronous=NORMAL`,
`foreign_keys=ON`.

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    name TEXT, ext TEXT, mime TEXT, size INTEGER, mtime REAL,
    summary TEXT, category TEXT, language TEXT,
    tags TEXT, entities TEXT,       -- comma-joined for display + FTS
    content TEXT,                   -- extracted text (capped)
    indexed_at REAL, ai_tagged INTEGER
);

-- External-content FTS5 mirror, kept in sync by AFTER INSERT/UPDATE/DELETE triggers.
CREATE VIRTUAL TABLE files_fts USING fts5(
    name, path, summary, tags, entities, content,
    content='files', content_rowid='id', tokenize='unicode61'
);

CREATE TABLE embeddings (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    dim INTEGER,
    vector BLOB                     -- float32 little-endian
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
```

**Incremental detection:** `needs_reindex(path, mtime, size)` compares the
stored `mtime`/`size`; unchanged files are skipped. Upserts use
`ON CONFLICT(path) DO UPDATE` so a file's `id` (and thus its embedding) stays
stable, and the FTS update trigger fires.

**Vectors** are stored as raw `float32` bytes and loaded into a single NumPy
matrix per query for brute-force cosine similarity — simple and fast enough for
typical libraries (swap in an ANN index later for very large ones).

## Search ranking

- **Keyword:** SQLite FTS5 `bm25()` (lower = better; negated for a
  higher-is-better score). Queries are tokenized and prefix-matched
  (`"term"*`), joined with implicit AND.
- **Semantic:** cosine similarity between the query embedding and each stored
  vector. A dimension-mismatch guard returns no results if the embedding model
  changed since indexing.
- **Hybrid (default):** [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormack/cormacksigir09-rrf.pdf)
  with `k=60`, summing `1/(k + rank)` across both ranked lists. RRF avoids having
  to normalize BM25 and cosine onto the same scale.

## Concurrency model

- Indexing uses a `ThreadPoolExecutor` (`max_workers`, default 4). Threads are a
  good fit because the work is I/O-bound: file reads and Ollama HTTP calls
  release the GIL.
- All DB access goes through `Index`, serialized by a re-entrant lock, so writes
  from worker threads are safe.
- The watcher runs the observer plus a single debounce/worker thread that
  coalesces rapid events per path before re-indexing.

## Exclusion rules

Defined in `scanner.py` and applied while walking:

- names starting with `.` (when `exclude_hidden`),
- directory names in `exclude_dir_names` (AppData, node_modules, …),
- OS noise files (`desktop.ini`, `ntuser.dat`, `Thumbs.db`, …),
- reparse points / junctions (skipped to avoid Windows symlink loops).

`is_excluded_path()` applies the same logic to absolute paths (checking
ancestors too) so the watcher ignores events under excluded trees. The default
index lives in the hidden `~/.filesearch/`, so it is never indexed by itself.

## `llm-checker` integration

`llm-checker recommend` prints a boxed report. `llm_checker.parse_recommendations`
strips ANSI and the box prefix (`│`), recognizes headers of the form
`Display (Canonical):` (and a `BEST OVERALL:` line), and extracts each
`ollama pull <model>` command. `choose_models` then maps categories to roles:

- **text model** ← `coding` → `reasoning` → `general` → `chat` (first available),
- **vision model** ← `multimodal` / `vision`.

If `llm-checker` is unavailable or unparseable, sensible fallback models are used
and everything remains overridable via config/flags.

## Extending filesearch

| Want to… | Edit |
|---|---|
| Read a new file type | `extract.py` — add the extension + a reader returning `Extracted("text", …)` |
| Add a CLI command | `cli.py` — add a `@app.command()` |
| Add a search filter | `db.py` `Index._apply_filters` + surface in `search.py` / web API |
| Change tag schema | `models.py` `TagResult` + the prompt in `ollama_client.py` |
| Swap the vector search | `db.py` `load_embeddings` + `search.py` `_semantic_ranked` |
