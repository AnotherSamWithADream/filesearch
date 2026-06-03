"""filesearch — AI-based file system search.

Scans your files, tags them with a local Ollama model (selected for your
hardware via ``llm-checker``), indexes everything into SQLite (full-text +
semantic vectors), and lets you search by keyword or meaning from a CLI,
a local web UI, or a desktop window.
"""

__version__ = "0.1.0"
