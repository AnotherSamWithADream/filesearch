"""Native desktop window (pywebview) wrapping the local web UI.

Starts the FastAPI app on a free localhost port in a background thread, then
opens it in a WebView2 window. The same UI as ``filesearch serve``.
"""

from __future__ import annotations

import socket
import threading
import time

from .config import Config


def _free_port(host: str = "127.0.0.1") -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_desktop(
    cfg: Config,
    host: str = "127.0.0.1",
    port: int | None = None,
    title: str = "filesearch",
) -> None:
    import uvicorn
    import webview

    from .web.server import create_app

    port = port or _free_port(host)
    server = uvicorn.Server(
        uvicorn.Config(create_app(cfg), host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to come up before pointing the window at it.
    for _ in range(200):
        if getattr(server, "started", False):
            break
        time.sleep(0.05)

    webview.create_window(title, f"http://{host}:{port}", width=1040, height=780)
    try:
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=3)
