"""Configuration: defaults, persistence, and the on-disk layout.

Config lives at ``~/.filesearch/config.json`` and the index DB at
``~/.filesearch/index.db`` by default. Everything is overridable.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

APP_DIR = Path.home() / ".filesearch"
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_DB_PATH = APP_DIR / "index.db"

# Directory names that are never worth AI-indexing. The leading-dot rule is
# handled separately (see ``Config.exclude_hidden``); these are the noisy
# non-hidden dirs found under a Windows/macOS/Linux home folder.
DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = (
    "AppData",
    "Application Data",
    "Local Settings",
    "$RECYCLE.BIN",
    "System Volume Information",
    "OneDriveTemp",
    "node_modules",
    "__pycache__",
    "site-packages",
    "venv",
    "env",
    "dist",
    "build",
    "target",
    "Library",            # macOS noise if run there
    ".venv",              # also covered by exclude_hidden, listed for clarity
)


class Config(BaseModel):
    """User-tunable settings for scanning, indexing, and the AI models."""

    # --- what to scan -------------------------------------------------------
    scan_roots: list[str] = Field(default_factory=lambda: [str(Path.home())])
    exclude_hidden: bool = True  # skip any file/dir whose name starts with '.'
    exclude_dir_names: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXCLUDE_DIRS)
    )
    # Files larger than this are indexed by metadata only (no content read).
    max_file_bytes: int = 25 * 1024 * 1024
    # Only this many characters of extracted text are sent to the model / stored.
    content_char_cap: int = 16_000

    # --- AI / models --------------------------------------------------------
    ollama_host: str = "http://localhost:11434"
    text_model: str | None = None       # set by `filesearch setup`
    vision_model: str | None = None      # set by `filesearch setup`
    embed_model: str = "nomic-embed-text"
    index_images: bool = True
    enable_ai_tagging: bool = True
    enable_embeddings: bool = True

    # --- engine -------------------------------------------------------------
    db_path: str = str(DEFAULT_DB_PATH)
    max_workers: int = 4

    def db_file(self) -> Path:
        return Path(self.db_path)


def load_config() -> Config:
    """Load config from disk, or return defaults if none exists yet."""
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return Config(**data)
        except Exception:
            # Corrupt config shouldn't be fatal — fall back to defaults.
            return Config()
    return Config()


def save_config(cfg: Config) -> Path:
    """Persist config to ``~/.filesearch/config.json`` and return its path."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg.model_dump(), indent=2), encoding="utf-8"
    )
    return CONFIG_PATH
