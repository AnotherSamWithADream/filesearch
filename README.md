# filesearch

**AI-based file system search.** It scans your files, reads their contents, and
uses a **local AI model** to tag and summarize each one — then lets you search
everything by keyword *or by meaning* from a CLI, a local web UI, or a desktop
window. Nothing leaves your machine.

The right model for *your* hardware is chosen automatically with
[`llm-checker`](https://www.npmjs.com/package/llm-checker), and the model itself
runs locally through [Ollama](https://ollama.com).

```
                       ┌─────────────┐   recommends    ┌──────────────┐
                       │ llm-checker │ ───────────────▶│    Ollama    │
                       └─────────────┘  text + vision  │ (local model)│
                                            models      └──────┬───────┘
                                                               │ tag / caption / embed
   scan files ──▶ extract text ──▶ ─────────────────────────▶ ┴ ──▶ SQLite index
   (home folder)  (pdf/docx/...)         AI tagging              (FTS5 + vectors)
                                                                      │
                                                  keyword + semantic search
                                                                      │
                                                   CLI · Web UI · Desktop
```

## Requirements

- **Python 3.10+**
- **Node.js + npm** (to run `llm-checker`)
- **[Ollama](https://ollama.com)** installed and running (the AI models run here)

> All four are detected automatically; `filesearch setup` will install
> `llm-checker` for you if it's missing.

## Install

```powershell
# from the project directory
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

This installs the `filesearch` command into the virtualenv
(`.venv\Scripts\filesearch.exe`).

## Quick start

```powershell
# 1. Pick + download the best models for your hardware (uses llm-checker)
filesearch setup

# 2. Index your files (incremental — only changed files are re-read)
filesearch scan

# 3. Search
filesearch query "tax documents from last year"
filesearch serve        # …or open the web UI in a browser
filesearch gui          # …or open the native desktop window
```

`setup` runs `llm-checker recommend`, parses its per-category picks, maps them
to roles (a **text** model for documents/code, a **vision** model for images),
and `ollama pull`s them. Embeddings (for semantic search) use
`nomic-embed-text`. You can override any of this — see below.

## Commands

| Command | What it does |
|---|---|
| `filesearch setup` | Detect/choose models via `llm-checker`, pull them, write config |
| `filesearch scan` | Walk the scan roots and index files (incremental) |
| `filesearch watch` | Continuously re-index as files are created/changed/deleted |
| `filesearch query "..."` | Search the index (`--mode hybrid\|keyword\|semantic`) |
| `filesearch status` | Show index stats, models, and Ollama connectivity |
| `filesearch serve` | Serve the web UI (`--host`, `--port`) |
| `filesearch gui` | Open the native desktop search window |

Useful flags:

- `setup --small` — use small, fast models (`llama3.2:3b`, `moondream`) for a
  quick start with minimal download.
- `setup --text-model X --vision-model Y --embed-model Z` — force specific models.
- `setup --no-vision` / `--no-embeddings` — skip image indexing / semantic search.
- `setup --root C:\Users\me\Documents --root D:\Projects` — set scan roots.
- `scan --limit 200` — index only the first N files (handy for a trial run).
- `query "..." --ext pdf,docx --category finance --json`.

## How search works

- **keyword** — SQLite **FTS5** full-text search over filename, path, summary,
  AI tags, entities, and extracted content (BM25 ranked).
- **semantic** — cosine similarity over embeddings, so *"money a client owes us"*
  finds an invoice even with no shared words.
- **hybrid** (default) — both, merged with Reciprocal Rank Fusion.

## What gets indexed

Walks your **home folder** by default and reads content from text/code, PDF,
DOCX, XLSX, PPTX, and (with a vision model) images. Other files are indexed by
metadata only.

**Excluded** automatically:

- anything whose name starts with `.` (e.g. `.ssh`, `.claude`, dotfiles),
- noisy directories: `AppData`, `node_modules`, `__pycache__`, `$RECYCLE.BIN`,
  build/venv dirs, etc. (configurable),
- OS junk (`desktop.ini`, `ntuser.dat`, …) and reparse-point/junction loops.

## Configuration

Stored at `~/.filesearch/config.json` (the index DB lives next to it at
`~/.filesearch/index.db`). Edit it directly or via `setup` flags. Key fields:

| field | meaning |
|---|---|
| `scan_roots` | folders to index (default: your home folder) |
| `exclude_hidden` | skip dot-prefixed names (default `true`) |
| `exclude_dir_names` | directory names to skip |
| `max_file_bytes` | files larger than this are metadata-only (default 25 MB) |
| `content_char_cap` | how much text per file is sent to the model / stored |
| `text_model` / `vision_model` / `embed_model` | Ollama models |
| `index_images` / `enable_embeddings` / `enable_ai_tagging` | feature toggles |

## Continuous indexing

`filesearch watch` starts a `watchdog` observer over your scan roots and
re-indexes files as they change (debounced). It watches each non-excluded
top-level subfolder, so heavy directories like `AppData` are never observed.

## Notes & limitations

- **Scope vs. speed.** AI-tagging *every* file in a large home folder is slow
  (each file is a model call). For a first run, point `--root` at a few folders,
  or use `--small`, then widen later. Re-scans are incremental.
- **Models must be pulled.** If the configured model isn't in Ollama yet, files
  are still indexed by filename/content; run `filesearch setup` to enable AI tags.
- Tag quality depends on the chosen local model. Malformed model JSON degrades
  gracefully to a best-effort summary rather than failing.

## Development

End-to-end smoke tests (no network for the first; the rest use local Ollama):

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test.py        # core: scan→extract→index→search
.\.venv\Scripts\python.exe scripts\ai_smoke_test.py     # AI tagging + semantic search
.\.venv\Scripts\python.exe scripts\web_smoke_test.py    # web API + static UI
.\.venv\Scripts\python.exe scripts\watch_smoke_test.py  # live file watching
```
