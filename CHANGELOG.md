# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/).

## [0.1.0-beta] - 2026-06-03

First public beta. 🎉

### Added
- **AI tagging** of files using a local [Ollama](https://ollama.com) model:
  summary, topical tags, category, entities, and language per file.
- **Automatic model selection** for the host's hardware via
  [`llm-checker`](https://www.npmjs.com/package/llm-checker) (`setup` parses its
  recommendations and pulls a text model + a vision model).
- **Content extraction** for plain text & code, PDF, DOCX, XLSX, PPTX, and
  images (vision model).
- **SQLite index** with an FTS5 full-text mirror (kept in sync by triggers) and
  a vector-embeddings table for semantic search.
- **Three search modes** — `keyword` (BM25), `semantic` (cosine over
  embeddings), and `hybrid` (Reciprocal Rank Fusion) — with extension, category,
  date, and size filters.
- **Three interfaces** over one shared core: a `typer` **CLI**, a **FastAPI web
  UI**, and a **pywebview desktop** window.
- **Continuous watching** (`watch`) that incrementally re-indexes files as they
  are created, modified, or deleted (debounced).
- **Smart exclusions**: dotfiles/dot-directories, `AppData` and other noisy
  folders, OS junk files, and reparse-point/junction loops.
- **Incremental scans** keyed on file size + modified time, with pruning of
  deleted files.
- CLI commands: `setup`, `scan`, `watch`, `query`, `status`, `serve`, `gui`.
- End-to-end smoke tests for the core pipeline, AI tagging + semantic search,
  the web API, and the file watcher.

### Security
- **Web UI (XSS):** result actions no longer interpolate file paths into inline
  `onclick` handlers (a single quote in a file name could break out and run
  script in the local UI's origin). Paths are now passed via HTML-escaped
  `data-path` attributes with event delegation.
- **Web API (DNS rebinding):** added `TrustedHostMiddleware` so the local server
  only accepts `localhost`/`127.0.0.1` `Host` headers by default, blocking
  rebinding attacks that could otherwise reach `/api/search` and `/api/open`
  cross-origin. Explicitly binding `--host` to a non-local address opts out.

### Known limitations
- Developed and tested primarily on **Windows 11**; macOS/Linux are supported by
  the code but less tested.
- Vision (image) tagging is implemented but was not exercised against a live
  vision model during initial development.
- Indexing a very large tree for the first time is slow (one model call per
  file); start narrow with `--root`/`--small` and widen later.

[0.1.0-beta]: https://github.com/AnotherSamWithADream/filesearch/releases/tag/v0.1.0-beta
