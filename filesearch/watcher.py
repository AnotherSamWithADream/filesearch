"""Continuous file watching via ``watchdog``.

Events are coalesced per path and debounced (a burst of writes to one file
re-indexes it once, after it settles). To avoid drowning in noise from
directories we never index (notably ``AppData``), we schedule the watch on each
*non-excluded* top-level subfolder rather than the whole root recursively.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import Config
from .indexer import Indexer
from .scanner import _is_reparse, is_excluded_path

EventFn = Callable[[dict], None]


class _Handler(FileSystemEventHandler):
    def __init__(self, emit: Callable[[str, str, bool], None]):
        self._emit = emit

    def on_created(self, event):
        if not event.is_directory:
            self._emit("upsert", event.src_path, False)

    def on_modified(self, event):
        if not event.is_directory:
            self._emit("upsert", event.src_path, False)

    def on_moved(self, event):
        self._emit("delete", event.src_path, event.is_directory)
        if not event.is_directory:
            self._emit("upsert", event.dest_path, False)

    def on_deleted(self, event):
        self._emit("delete", event.src_path, event.is_directory)


class Watcher:
    def __init__(self, cfg: Config, debounce: float = 1.5):
        self.cfg = cfg
        self.debounce = debounce
        self.indexer = Indexer(cfg)
        self._observer = Observer()
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._pending: dict[str, tuple[str, bool, float]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- event intake ------------------------------------------------------
    def _emit(self, action: str, path: str, is_dir: bool) -> None:
        if action == "upsert" and is_excluded_path(path, self.cfg):
            return
        self._queue.put((action, path, is_dir, time.time()))

    # --- scheduling --------------------------------------------------------
    def _schedule_root(self, handler: _Handler, root: str) -> int:
        rp = Path(root)
        watched = 0
        try:
            # Top-level files in the root itself (not recursive).
            self._observer.schedule(handler, str(rp), recursive=False)
            watched += 1
        except Exception:
            pass
        exclude_lower = {d.lower() for d in self.cfg.exclude_dir_names}
        try:
            scan = os.scandir(str(rp))
        except (PermissionError, OSError):
            return watched
        with scan:
            for entry in scan:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if _is_reparse(entry):  # skip junctions (e.g. AppData links)
                        continue
                    name = entry.name
                    if self.cfg.exclude_hidden and name.startswith("."):
                        continue
                    if name.lower() in exclude_lower:
                        continue
                    self._observer.schedule(handler, entry.path, recursive=True)
                    watched += 1
                except (PermissionError, OSError):
                    continue
        return watched

    # --- worker loop -------------------------------------------------------
    def _worker(self, on_event: EventFn | None) -> None:
        while not self._stop.is_set():
            try:
                while True:
                    action, path, is_dir, ts = self._queue.get_nowait()
                    self._pending[path] = (action, is_dir, ts)
            except queue.Empty:
                pass

            now = time.time()
            ready = [
                (p, v) for p, v in list(self._pending.items()) if now - v[2] >= self.debounce
            ]
            for path, (action, is_dir, _ts) in ready:
                self._pending.pop(path, None)
                self._process(action, path, is_dir, on_event)

            self._stop.wait(0.3)

    def _process(self, action: str, path: str, is_dir: bool, on_event: EventFn | None) -> None:
        try:
            if action == "delete":
                if is_dir:
                    n = self.indexer.index.delete_under(path)
                    evt = {"action": "delete_dir", "path": path, "count": n}
                else:
                    self.indexer.index.delete_by_path(path)
                    evt = {"action": "delete", "path": path}
            else:
                res = self.indexer.index_path(path)
                if res is None:
                    return
                evt = {"action": "index", "path": path, "result": res}
            if on_event:
                on_event(evt)
        except Exception as e:  # noqa: BLE001
            if on_event:
                on_event({"action": "error", "path": path, "error": str(e)})

    # --- lifecycle ---------------------------------------------------------
    def start(self, on_event: EventFn | None = None) -> int:
        handler = _Handler(self._emit)
        watched = 0
        for root in self.cfg.scan_roots:
            if Path(root).exists():
                watched += self._schedule_root(handler, root)
        self._observer.start()
        self._thread = threading.Thread(target=self._worker, args=(on_event,), daemon=True)
        self._thread.start()
        return watched

    def stop(self) -> None:
        self._stop.set()
        try:
            self._observer.stop()
            self._observer.join(timeout=5)
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=5)

    def run_forever(self, on_event: EventFn | None = None) -> int:
        """Start watching and block until interrupted (Ctrl-C)."""
        watched = self.start(on_event)
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
        return watched
