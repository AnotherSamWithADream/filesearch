"""Filesystem walker.

Iteratively walks the configured scan roots and yields :class:`FileMeta` for
every file that passes the exclusion rules:

  * anything whose name starts with ``.`` (when ``exclude_hidden``),
  * directories named in ``exclude_dir_names`` (AppData, node_modules, ...),
  * a small set of OS noise files (desktop.ini, ntuser.dat, ...),
  * reparse points / junctions (skipped to avoid the classic Windows
    "Application Data" -> AppData loop).

Permission errors are swallowed per-entry so a single locked folder can't stop
the scan. The same rules are exposed via :func:`is_excluded_path` for the
file watcher.
"""

from __future__ import annotations

import mimetypes
import os
import stat
from collections.abc import Iterator
from pathlib import Path

from .config import Config
from .models import FileMeta

# Well-known Windows/OS files that are never useful to index.
NOISE_FILES = {
    "desktop.ini", "thumbs.db", "thumbs.db:encryptable", "ehthumbs.db",
    "ntuser.dat", "ntuser.ini", "ntuser.dat.log1", "ntuser.dat.log2",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", ".ds_store",
}

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_reparse(entry: os.DirEntry) -> bool:
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs:
        return bool(attrs & _REPARSE)
    return entry.is_symlink()


def _excluded_dir(name: str, cfg: Config, exclude_lower: set[str]) -> bool:
    if cfg.exclude_hidden and name.startswith("."):
        return True
    return name.lower() in exclude_lower


def _excluded_file(name: str, cfg: Config) -> bool:
    if cfg.exclude_hidden and name.startswith("."):
        return True
    return name.lower() in NOISE_FILES


def _meta_from_entry(entry: os.DirEntry) -> FileMeta | None:
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    ext = os.path.splitext(entry.name)[1].lower()
    mime, _ = mimetypes.guess_type(entry.name)
    return FileMeta(
        path=entry.path,
        name=entry.name,
        ext=ext,
        size=st.st_size,
        mtime=st.st_mtime,
        mime=mime,
    )


def iter_files(cfg: Config) -> Iterator[FileMeta]:
    """Yield :class:`FileMeta` for every indexable file under the scan roots."""
    exclude_lower = {d.lower() for d in cfg.exclude_dir_names}
    for root in cfg.scan_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        stack: list[str] = [str(root_path)]
        while stack:
            current = stack.pop()
            try:
                scan = os.scandir(current)
            except (PermissionError, OSError, NotADirectoryError):
                continue
            with scan:
                for entry in scan:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if _is_reparse(entry):
                                continue
                            if _excluded_dir(entry.name, cfg, exclude_lower):
                                continue
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if _excluded_file(entry.name, cfg):
                                continue
                            meta = _meta_from_entry(entry)
                            if meta is not None:
                                yield meta
                    except (PermissionError, OSError):
                        continue


def _within(path: Path, root: Path) -> bool:
    try:
        a = os.path.normcase(os.path.abspath(str(path)))
        b = os.path.normcase(os.path.abspath(str(root)))
        return a == b or a.startswith(b + os.sep)
    except Exception:
        return False


def is_excluded_path(path: str, cfg: Config) -> bool:
    """True if ``path`` should NOT be indexed (used by the watcher)."""
    p = Path(path)
    if not any(_within(p, Path(r)) for r in cfg.scan_roots):
        return True
    if cfg.exclude_hidden and any(part.startswith(".") for part in p.parts):
        return True
    exclude_lower = {d.lower() for d in cfg.exclude_dir_names}
    if any(part.lower() in exclude_lower for part in p.parts[:-1]):
        return True
    if p.name.lower() in NOISE_FILES:
        return True
    return False
