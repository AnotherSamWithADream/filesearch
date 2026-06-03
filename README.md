<div align="center">

# 🔎 filesearch

**Find any file by what's *in* it — not just its name.**

filesearch scans your files, uses a **local AI model** to read and tag each one,
and lets you search everything by **keyword or meaning** from a command line, a
web page, or a desktop app. Your files never leave your computer.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Status: beta](https://img.shields.io/badge/status-beta-orange.svg)](https://github.com/AnotherSamWithADream/filesearch/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#requirements)
[![Powered by Ollama](https://img.shields.io/badge/AI-Ollama-black.svg)](https://ollama.com)

</div>

> **Beta.** filesearch is new and developed/tested primarily on **Windows 11**.
> macOS and Linux are supported by the code but less battle-tested. Expect rough
> edges, and please [file issues](https://github.com/AnotherSamWithADream/filesearch/issues)!

---

## Table of contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start (3 steps)](#quick-start-3-steps)
- [Using filesearch](#using-filesearch)
  - [Command line](#1-command-line)
  - [Web UI](#2-web-ui)
  - [Desktop app](#3-desktop-app)
- [Search modes](#search-modes)
- [Command reference](#command-reference)
- [Configuration](#configuration)
- [What gets indexed (and what doesn't)](#what-gets-indexed-and-what-doesnt)
- [Performance & scaling tips](#performance--scaling-tips)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Privacy](#privacy)
- [Development](#development)
- [Roadmap](#roadmap)
- [License](#license)

---

## What it does

Traditional file search matches **file names**. filesearch matches **content and
meaning**:

- 🧠 **AI tagging** — a local model reads each file and produces a short summary,
  topical tags, a category (finance, code, note…), and key entities.
- 🔤 **Keyword search** — fast full-text search over names, content, and tags.
- ✨ **Semantic search** — find files by *meaning*. Searching
  *"money a client owes us"* surfaces an invoice even if it never says "money".
- 🖼️ **Reads many formats** — plain text & code, **PDF, DOCX, XLSX, PPTX**, and
  images (via a vision model).
- 🔁 **Always current** — an optional watcher re-indexes files the moment they
  change.
- 🖥️ **Three ways to search** — a CLI, a local web page, and a desktop window.
- 🔒 **100% local & private** — the AI runs on your machine through
  [Ollama](https://ollama.com). Nothing is uploaded anywhere.

The best model for **your** hardware is picked automatically using
[`llm-checker`](https://www.npmjs.com/package/llm-checker).

## How it works

```
                    ┌──────────────┐  recommends models   ┌───────────────┐
                    │  llm-checker  │ ───────────────────▶ │     Ollama     │
                    │ (scans your   │   text + vision      │ (runs the AI   │
                    │   hardware)   │                      │  model locally)│
                    └──────────────┘                       └───────┬───────┘
                                                                   │ tag · caption · embed
  ┌──────────┐   ┌─────────────┐   ┌───────────────┐              ▼
  │  scan    │──▶│  extract    │──▶│  AI tagging   │──▶  SQLite index (FTS5 + vectors)
  │  files   │   │  text/pages │   │  + embeddings │              │
  └──────────┘   └─────────────┘   └───────────────┘              ▼
                                                       keyword · semantic · hybrid search
                                                                   │
                                                       ┌───────────┴───────────┐
                                                       │  CLI · Web UI · Desktop │
                                                       └─────────────────────────┘
```

## Requirements

| Tool | Why | Check it's installed |
|---|---|---|
| **[Python 3.10+](https://www.python.org/downloads/)** | runs filesearch | `python --version` |
| **[Ollama](https://ollama.com/download)** | runs the AI models locally | `ollama --version` |
| **[Node.js + npm](https://nodejs.org/)** | runs `llm-checker` to pick models | `node --version` |

> 💡 You don't need a fancy GPU. `llm-checker` picks a model that fits your
> machine, and you can always choose a small one with `filesearch setup --small`.
> `llm-checker` itself is installed for you automatically.

## Installation

**1. Install the prerequisites above** (Python, Ollama, Node.js) and make sure
**Ollama is running** (launch the Ollama app, or run `ollama serve`).

**2. Get filesearch and install it into a virtual environment:**

<details open>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
git clone https://github.com/AnotherSamWithADream/filesearch.git
cd filesearch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```
</details>

<details>
<summary><b>macOS / Linux (bash)</b></summary>

```bash
git clone https://github.com/AnotherSamWithADream/filesearch.git
cd filesearch
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```
</details>

Once the venv is **activated**, the `filesearch` command is available. (Not
activated? Use the full path: `.\.venv\Scripts\filesearch` on Windows or
`./.venv/bin/filesearch` on macOS/Linux.)

Verify it:

```console
$ filesearch --help
```

## Quick start (3 steps)

```console
$ filesearch setup      # 1. pick + download the best AI models for your PC
$ filesearch scan       # 2. read and index your files
$ filesearch query "tax documents from last year"   # 3. search!
```

That's it. Prefer a UI? Run `filesearch serve` (opens in your browser) or
`filesearch gui` (desktop window).

> **Express setup.** In a hurry or on a small machine? Use small, fast models
> and index just one folder first:
>
> ```console
> $ filesearch setup --small --root "C:\Users\you\Documents"
> $ filesearch scan
> ```

What `setup` does: it runs `llm-checker recommend`, reads the recommended models
for your hardware, maps them to roles — a **text** model (documents & code) and a
**vision** model (images) — and downloads them via Ollama. Semantic-search
embeddings use `nomic-embed-text`.

## Using filesearch

### 1. Command line

```console
$ filesearch query "quarterly revenue spreadsheet"
2 results · hybrid

sales_q3.xlsx  hybrid · 100% · 18.4 KB
  C:\Users\you\Documents\finance\sales_q3.xlsx
  Quarterly revenue and expense breakdown for Q3.
  #finance #revenue #spreadsheet

report.docx  semantic · 71% · 42.1 KB
  C:\Users\you\Documents\reports\report.docx
  Annual financial report; revenue grew 20% year over year.
  #finance #report
```

Filter and tune:

```console
$ filesearch query "invoice" --ext pdf,docx        # only PDFs and Word docs
$ filesearch query "vacation photos" --category image
$ filesearch query "auth bug" --mode semantic -n 5  # meaning-only, top 5
$ filesearch query "budget" --json                  # machine-readable output
```

### 2. Web UI

```console
$ filesearch serve
filesearch web UI → http://127.0.0.1:8765
```

Open the URL in your browser. You get a search box with **Hybrid / Keyword /
Semantic** modes, extension and category filters, highlighted snippets, and
**Open** / **Show in folder** buttons for every result.

### 3. Desktop app

```console
$ filesearch gui
```

The same search interface in a native window — no browser needed.

### Keep the index fresh automatically

```console
$ filesearch watch
Watching 6 location(s). Press Ctrl-C to stop.
indexed C:\Users\you\Documents\new_notes.md
removed  C:\Users\you\Documents\old_draft.txt
```

`watch` re-indexes files as you create, edit, or delete them.

## Search modes

| Mode | Finds matches by | Best for |
|---|---|---|
| `keyword` | exact words in names, content, tags (FTS5/BM25) | you know the words used |
| `semantic` | **meaning** (vector similarity) | you only remember the gist |
| `hybrid` *(default)* | both, fused together | everyday searching |

> Semantic and hybrid need embeddings, which require an embedding model
> (`nomic-embed-text`, pulled during `setup`). Without it, filesearch falls back
> to keyword search automatically.

## Command reference

| Command | Description | Key options |
|---|---|---|
| `setup` | Choose models (via `llm-checker`), download them, write config | `--small`, `--text-model`, `--vision-model`, `--embed-model`, `--no-vision`, `--no-embeddings`, `--root`, `--skip-pull`, `-y/--yes` |
| `scan` | Walk the scan roots and index files (incremental) | `--root`, `--limit N` |
| `watch` | Continuously re-index on file changes | `--root` |
| `query "..."` | Search the index | `--mode`, `-n/--limit`, `--ext`, `--category`, `--json` |
| `status` | Show index stats, models, and Ollama connectivity | — |
| `serve` | Serve the web UI | `--host`, `--port` |
| `gui` | Open the desktop search window | — |

Run `filesearch <command> --help` for the full option list of any command.

## Configuration

Settings live in a JSON file you can edit by hand or change with `setup` flags.

| OS | Config file | Index database |
|---|---|---|
| Windows | `C:\Users\<you>\.filesearch\config.json` | `…\.filesearch\index.db` |
| macOS/Linux | `~/.filesearch/config.json` | `~/.filesearch/index.db` |

| Field | Default | Meaning |
|---|---|---|
| `scan_roots` | your home folder | folders to index |
| `exclude_hidden` | `true` | skip names starting with `.` |
| `exclude_dir_names` | AppData, node_modules, … | directory names to skip |
| `max_file_bytes` | `26214400` (25 MB) | larger files are indexed by metadata only |
| `content_char_cap` | `16000` | how much text per file is read/sent to the model |
| `text_model` | *(set by setup)* | Ollama model for documents & code |
| `vision_model` | *(set by setup)* | Ollama model for images |
| `embed_model` | `nomic-embed-text` | model for semantic embeddings |
| `index_images` | `true` | analyze images with the vision model |
| `enable_ai_tagging` | `true` | use the AI model for tags/summaries |
| `enable_embeddings` | `true` | compute embeddings for semantic search |
| `ollama_host` | `http://localhost:11434` | where Ollama is listening |
| `max_workers` | `4` | parallel indexing workers |

## What gets indexed (and what doesn't)

**Indexed (content read):** text & code, `.pdf`, `.docx`, `.xlsx`, `.pptx`, and
images (`.png`, `.jpg`, …) when a vision model is available. Everything else is
indexed by metadata (name, size, date).

**Skipped automatically:**

- anything whose name starts with `.` (e.g. `.ssh`, `.git`, dotfiles),
- noisy folders: `AppData`, `node_modules`, `__pycache__`, `$RECYCLE.BIN`,
  `venv`, `build`, `dist`, … (all configurable),
- OS junk (`desktop.ini`, `ntuser.dat`, `Thumbs.db`),
- symlink/junction loops (e.g. the Windows `Application Data → AppData` junction).

## Performance & scaling tips

- **AI tagging is one model call per file.** Indexing an entire home folder for
  the first time can take a while. Start small and grow:
  ```console
  $ filesearch setup --small --root "C:\Users\you\Documents"
  $ filesearch scan
  ```
- **Re-scans are incremental** — only new or changed files (by size + modified
  time) are re-read, so day-to-day scans are fast.
- **Pick a model that fits your RAM/VRAM.** `llm-checker` does this for you;
  `--small` forces lightweight models (`llama3.2:3b`, `moondream`).
- **Don't need images or semantic search?** `filesearch setup --no-vision
  --no-embeddings` makes indexing much faster.

## Troubleshooting

<details>
<summary><b>"Ollama is not reachable"</b></summary>

Ollama isn't running. Launch the Ollama app, or run `ollama serve` in a terminal,
then retry. Check the host matches `ollama_host` in your config
(default `http://localhost:11434`).
</details>

<details>
<summary><b>Scan says "Text model … not pulled" / files have no tags</b></summary>

The configured model hasn't been downloaded yet. Run `filesearch setup` (or
`ollama pull <model>`). Files are still indexed by name/content in the meantime —
re-run `scan` after the model is available to add AI tags.
</details>

<details>
<summary><b>"llm-checker not found"</b></summary>

`setup` installs it automatically (`npm install -g llm-checker`). If that fails,
install it yourself and ensure Node.js/npm are on your `PATH`. You can also skip
detection entirely: `filesearch setup --text-model <m> --vision-model <m>`.
</details>

<details>
<summary><b>Semantic search returns nothing</b></summary>

Semantic search needs the embedding model. Confirm `nomic-embed-text` is pulled
(`ollama list`) and that `enable_embeddings` is `true`, then re-`scan`. Check
`filesearch status` — it shows whether semantic search is available.
</details>

<details>
<summary><b>The web UI port is already in use</b></summary>

Pick another port: `filesearch serve --port 9000`.
</details>

<details>
<summary><b>Indexing feels slow</b></summary>

That's the AI model working through each file. Use `--small`, narrow your
`--root`, or disable images/embeddings (see Performance tips above).
</details>

## FAQ

**Does my data leave my computer?** No. All analysis happens locally via Ollama.
The only network use is downloading models and the `llm-checker`/`npm` install.

**Do I need a GPU?** No — a CPU works with a small model. A GPU is faster.

**Can I index a specific folder instead of everything?**
Yes: `filesearch setup --root "D:\Projects"` (repeat `--root` for more), or edit
`scan_roots` in the config.

**How do I re-index from scratch?** Delete the index DB
(`~/.filesearch/index.db`) and run `filesearch scan` again.

**Which models are used?** Whatever `llm-checker` recommends for your hardware
(a text model + a vision model), plus `nomic-embed-text` for embeddings. Override
any of them with `setup` flags or in the config.

## Privacy

filesearch is designed to be **local-first**. File contents are read on your
machine, sent only to your local Ollama server, and stored only in your local
SQLite index. There is no telemetry and no cloud service.

## Development

```console
# from an activated venv
pip install -e .

# end-to-end smoke tests (first needs no network; others use local Ollama)
python scripts/smoke_test.py        # core: scan → extract → index → search
python scripts/ai_smoke_test.py     # AI tagging + semantic search
python scripts/web_smoke_test.py    # web API + static UI
python scripts/watch_smoke_test.py  # live file watching
```

Project internals are documented in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
Contributions are welcome — see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Roadmap

- [ ] Broader macOS/Linux testing
- [ ] Packaged installers / `pipx` distribution
- [ ] Run `watch` as a background service
- [ ] OCR for scanned/image-only PDFs
- [ ] Result previews and thumbnails in the UI
- [ ] Approximate-nearest-neighbor index for very large libraries

See the [CHANGELOG](CHANGELOG.md) for release history.

## License

[MIT](LICENSE) © 2026 Samit Mohnot

## Acknowledgements

Built on [Ollama](https://ollama.com) and
[`llm-checker`](https://github.com/Pavelevich/llm-checker).
