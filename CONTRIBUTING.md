# Contributing to filesearch

Thanks for your interest! filesearch is in **beta**, so bug reports, ideas, and
pull requests are all very welcome.

## Ways to help

- 🐛 **Report bugs** — open an [issue](https://github.com/AnotherSamWithADream/filesearch/issues)
  with your OS, Python version, what you ran, and what happened (paste the
  output of `filesearch status` if relevant).
- 💡 **Suggest features** — open an issue describing the use case.
- 🧪 **Test on macOS/Linux** — this is the least-exercised area; reports help a lot.
- 🔧 **Send a pull request** — see below.

## Development setup

```bash
git clone https://github.com/AnotherSamWithADream/filesearch.git
cd filesearch
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
pip install -e .
```

You'll also need [Ollama](https://ollama.com) running and at least a small model
(`ollama pull llama3.2:3b` and `ollama pull nomic-embed-text`) to exercise the
AI paths.

## Running the tests

The repo ships self-contained smoke tests in `scripts/`:

```bash
python scripts/smoke_test.py        # core: scan → extract → index → search (no network)
python scripts/ai_smoke_test.py     # AI tagging + semantic search (needs Ollama)
python scripts/web_smoke_test.py    # web API + static UI
python scripts/watch_smoke_test.py  # live file watching
```

Each script creates files in a temp directory, exercises a slice of the system,
asserts the expected results, and cleans up. Please make sure they pass (and add
to them) before opening a PR.

## Code style

- Target **Python 3.10+**; keep imports standard-library-first.
- Match the surrounding style: type hints, `from __future__ import annotations`,
  small focused functions, and module docstrings explaining the "why".
- Be defensive in file I/O and model calls — a single bad file or a flaky model
  response must never abort a whole scan. Prefer returning a best-effort result
  over raising.
- Keep all functionality **local and private**; don't add network calls beyond
  the local Ollama server and model/`npm` downloads.

## Project layout

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full module map and
data flow. Common extension points:

- **New file type to read** → add the extension and a reader in
  `filesearch/extract.py`.
- **New CLI command** → add a `@app.command()` in `filesearch/cli.py`.
- **New search filter** → extend `Index._apply_filters` in `filesearch/db.py`
  and surface it in `filesearch/search.py` / the web API.

## Pull request checklist

1. Branch off `main`.
2. Keep changes focused; explain the motivation in the PR description.
3. Run the smoke tests (and add coverage for new behavior).
4. Update the `README`/`CHANGELOG`/`docs` if you change user-facing behavior.

## Reporting security issues

filesearch runs locally and stores data only on your machine. If you find a
security-relevant issue (e.g. a path-handling bug), please open an issue or
contact the maintainer rather than exploiting it.

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
