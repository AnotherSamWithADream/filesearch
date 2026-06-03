"""Command-line interface for filesearch.

    filesearch setup      pick + pull the AI models (via llm-checker) and save config
    filesearch scan       index your files
    filesearch watch      keep the index live as files change
    filesearch query ...  search the index
    filesearch status     show what's indexed
    filesearch serve      open the web UI in a browser
    filesearch gui        open the desktop window
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from . import llm_checker
from .config import CONFIG_PATH, Config, load_config, save_config
from .indexer import Indexer
from .ollama_client import OllamaClient
from .search import SearchEngine

# Windows consoles often default to cp1252, which can't encode some characters
# in file content or output glyphs. Force UTF-8 so output never crashes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

app = typer.Typer(
    help="AI-based file system search: scan, tag with a local model, and search.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# Small, fast models for --small (good for a quick test without big downloads).
SMALL_TEXT = "llama3.2:3b"
SMALL_VISION = "moondream"
SMALL_EMBED = "nomic-embed-text"


def _fmt_size(n: int) -> str:
    if not n:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}" if i else f"{int(f)} B"


def _pull_if_missing(client: OllamaClient, model: str) -> bool:
    """Pull a model with a progress bar unless it's already present."""
    if not model:
        return False
    if client.has_model(model):
        console.print(f"  [green]ok[/] {model} already available")
        return True
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as prog:
        task = prog.add_task(f"pull {model}", total=None)

        def on_progress(p: dict) -> None:
            total, completed = p.get("total"), p.get("completed")
            if total:
                prog.update(task, total=total, completed=completed or 0)
            else:
                prog.update(task, description=f"{model}: {p.get('status', '')}")

        try:
            client.pull(model, on_progress)
        except Exception as e:  # noqa: BLE001
            console.print(f"  [red]x failed to pull {model}: {e}[/]")
            return False
    console.print(f"  [green]ok[/] pulled {model}")
    return True


@app.command()
def setup(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept recommendations without prompting."),
    text_model: Optional[str] = typer.Option(None, help="Override the text model."),
    vision_model: Optional[str] = typer.Option(None, help="Override the vision model."),
    embed_model: Optional[str] = typer.Option(None, help="Override the embedding model."),
    small: bool = typer.Option(False, "--small", help="Use small fast models (good for testing)."),
    no_vision: bool = typer.Option(False, "--no-vision", help="Don't index images."),
    no_embeddings: bool = typer.Option(False, "--no-embeddings", help="Disable semantic search."),
    root: Optional[List[str]] = typer.Option(None, "--root", help="Scan root (repeatable). Default: home."),
    skip_pull: bool = typer.Option(False, "--skip-pull", help="Write config but don't pull models."),
    install_checker: bool = typer.Option(True, help="Install llm-checker if it's missing."),
) -> None:
    """Select the on-device models (via llm-checker) and write the config."""
    cfg = load_config()

    # 1. Ensure llm-checker is installed.
    if not llm_checker.is_installed():
        if install_checker:
            console.print("[yellow]llm-checker not found — installing (npm install -g llm-checker)…[/]")
            ok, out = llm_checker.install()
            console.print("[green]installed llm-checker[/]" if ok else f"[red]install failed:[/] {out[:400]}")
        else:
            console.print("[yellow]llm-checker not installed; using fallback model defaults.[/]")

    # 2. Discover hardware-appropriate models (skip if the user forced them).
    info = {"parsed": {}, "text_model": None, "vision_model": None, "used_fallback": False, "raw": ""}
    need_detect = not small and (text_model is None or vision_model is None)
    if need_detect:
        console.print("\n[bold]Detecting best models for your hardware…[/]")
        info = llm_checker.discover_models()
        if info["parsed"]:
            table = Table(title="llm-checker recommendations", show_edge=False)
            table.add_column("category", style="cyan")
            table.add_column("model", style="green")
            for cat, model in info["parsed"].items():
                if cat != "_loose":
                    table.add_row(cat, model)
            console.print(table)
        elif info["used_fallback"]:
            console.print("[yellow]Could not parse llm-checker output; using sensible defaults.[/]")
    else:
        console.print("[dim]Using specified models (skipping hardware detection).[/]")

    # 3. Resolve final model choices (override > small > discovered).
    final_text = text_model or (SMALL_TEXT if small else info["text_model"])
    final_vision = vision_model or (SMALL_VISION if small else info["vision_model"])
    final_embed = embed_model or (SMALL_EMBED if small else cfg.embed_model)

    console.print("\n[bold]Chosen models:[/]")
    console.print(f"  text   : [green]{final_text}[/]")
    console.print(f"  vision : [green]{final_vision}[/]" + ("  [dim](image indexing off)[/]" if no_vision else ""))
    console.print(f"  embed  : [green]{final_embed}[/]" + ("  [dim](semantic off)[/]" if no_embeddings else ""))

    if not yes and not skip_pull:
        if not typer.confirm("\nPull these models now?", default=True):
            skip_pull = True

    # 4. Pull models through Ollama.
    client = OllamaClient(cfg.ollama_host)
    if not skip_pull:
        if not client.ping():
            console.print(
                "[red]Ollama is not reachable at "
                f"{cfg.ollama_host}.[/] Start Ollama (run [bold]ollama serve[/] or open the "
                "Ollama app), then re-run [bold]filesearch setup[/]. Saving config for now."
            )
        else:
            console.print("\n[bold]Pulling models…[/]")
            _pull_if_missing(client, final_text)
            if not no_vision:
                _pull_if_missing(client, final_vision)
            if not no_embeddings:
                _pull_if_missing(client, final_embed)

    # 5. Persist config.
    cfg.text_model = final_text
    cfg.vision_model = final_vision
    cfg.embed_model = final_embed
    cfg.index_images = not no_vision
    cfg.enable_embeddings = not no_embeddings
    if root:
        cfg.scan_roots = list(root)
    path = save_config(cfg)
    console.print(f"\n[green]Config saved to[/] {path}")
    console.print("Next: [bold]filesearch scan[/] to index, then [bold]filesearch query \"...\"[/] or [bold]filesearch serve[/].")


@app.command()
def scan(
    limit: Optional[int] = typer.Option(None, help="Stop after indexing this many files (testing)."),
    root: Optional[List[str]] = typer.Option(None, "--root", help="Override scan roots for this run."),
) -> None:
    """Walk the scan roots and index files (incremental — only changed files)."""
    cfg = load_config()
    if root:
        cfg.scan_roots = list(root)
    console.print(f"[bold]Scanning:[/] {', '.join(cfg.scan_roots)}")
    indexer = Indexer(cfg)
    caps = indexer.capabilities()
    if not caps["ai"]:
        console.print(
            "[yellow]AI tagging is OFF[/] (Ollama unreachable or models missing). "
            "Files will be indexed by metadata only — run [bold]filesearch setup[/] first for AI tags."
        )
    elif not caps["text"]:
        console.print(f"[yellow]Text model '{cfg.text_model}' not pulled — run setup.[/]")

    counters = {"scanned": 0, "indexed": 0, "skipped": 0}
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as prog:
        task = prog.add_task("scanning…", total=None)

        def on_progress(evt: dict) -> None:
            if "scanning" in evt:
                counters["scanned"] = evt["scanned"]
            elif evt.get("ok") and not evt.get("skipped"):
                counters["indexed"] += 1
            prog.update(
                task,
                description=f"scanned {counters['scanned']} · indexed {counters['indexed']}",
            )

        # Pass capabilities we already probed by reusing the indexer.
        stats = indexer.run_scan(on_progress=on_progress, limit=limit)

    table = Table(show_edge=False, title="Scan complete")
    table.add_column("metric", style="cyan")
    table.add_column("count", justify="right", style="green")
    table.add_row("files scanned", str(stats["scanned"]))
    table.add_row("indexed this run", str(stats["indexed"]))
    table.add_row("AI-tagged this run", str(stats["reindexed"]))
    table.add_row("unchanged (skipped)", str(stats["skipped"]))
    table.add_row("pruned (deleted)", str(stats.get("pruned", 0)))
    table.add_row("errors", str(stats["errors"]))
    console.print(table)


@app.command()
def query(
    text: List[str] = typer.Argument(..., help="Search text."),
    mode: str = typer.Option("hybrid", help="hybrid | keyword | semantic"),
    limit: int = typer.Option(20, "--limit", "-n"),
    ext: Optional[str] = typer.Option(None, help="Filter by extension(s), comma-separated."),
    category: Optional[str] = typer.Option(None, help="Filter by AI category."),
    json_out: bool = typer.Option(False, "--json", help="Output raw JSON."),
) -> None:
    """Search the index by keyword, meaning, or both."""
    q = " ".join(text)
    cfg = load_config()
    engine = SearchEngine(cfg)
    filters: dict = {}
    if ext:
        filters["ext"] = [e.strip() for e in ext.split(",") if e.strip()]
    if category:
        filters["category"] = category
    hits = engine.search(q, limit=limit, mode=mode, filters=filters or None)

    if json_out:
        console.print_json(json.dumps([h.model_dump() for h in hits]))
        return

    if not hits:
        console.print("[dim]No matches.[/]")
        return
    console.print(f"[dim]{len(hits)} results · {mode}[/]\n")
    for h in hits:
        head = f"[bold]{h.name}[/]"
        meta = f"[dim]{h.match_type} · {int(h.score * 100)}% · {_fmt_size(h.size)}[/]"
        console.print(f"{head}  {meta}")
        console.print(f"  [dim]{h.path}[/]")
        if h.summary:
            console.print(f"  {h.summary}")
        if h.snippet:
            snip = h.snippet.replace("[[", "[yellow]").replace("]]", "[/yellow]")
            console.print(f"  [dim]…[/] {snip}")
        if h.tags or h.category:
            chips = " ".join(f"[cyan]#{t}[/]" for t in h.tags)
            cat = f"[magenta]{h.category}[/] " if h.category else ""
            console.print(f"  {cat}{chips}")
        console.print()


@app.command()
def status() -> None:
    """Show index statistics, configured models, and Ollama connectivity."""
    cfg = load_config()
    engine = SearchEngine(cfg)
    s = engine.index.stats()
    up = OllamaClient(cfg.ollama_host).ping()

    table = Table(show_edge=False, title="filesearch status")
    table.add_column("", style="cyan")
    table.add_column("", style="white")
    table.add_row("config", str(CONFIG_PATH))
    table.add_row("db", cfg.db_path)
    table.add_row("scan roots", "\n".join(cfg.scan_roots))
    table.add_row("files indexed", str(s["files"]))
    table.add_row("AI-tagged", str(s["ai_tagged"]))
    table.add_row("embedded", str(s["embedded"]))
    table.add_row("total size", _fmt_size(s["total_size"]))
    table.add_row("text model", cfg.text_model or "[dim]unset[/]")
    table.add_row("vision model", cfg.vision_model or "[dim]unset[/]")
    table.add_row("embed model", cfg.embed_model or "[dim]unset[/]")
    table.add_row("Ollama", "[green]online[/]" if up else "[red]offline[/]")
    console.print(table)


@app.command()
def watch(
    root: Optional[List[str]] = typer.Option(None, "--root", help="Override scan roots."),
) -> None:
    """Continuously re-index files as they are created, changed, or removed."""
    from .watcher import Watcher

    cfg = load_config()
    if root:
        cfg.scan_roots = list(root)
    watcher = Watcher(cfg)

    def on_event(evt: dict) -> None:
        action = evt.get("action")
        path = evt.get("path", "")
        if action == "index":
            res = evt.get("result") or {}
            if res.get("skipped"):
                return
            tag = "[green]indexed[/]" if res.get("ai_tagged") else "[blue]indexed (meta)[/]"
            console.print(f"{tag} {path}")
        elif action == "delete":
            console.print(f"[red]removed[/] {path}")
        elif action == "delete_dir":
            console.print(f"[red]removed dir[/] {path} ({evt.get('count', 0)} files)")
        elif action == "error":
            console.print(f"[red]error[/] {path}: {evt.get('error')}")

    n = watcher.start(on_event)
    console.print(f"[bold]Watching[/] {n} location(s). Press Ctrl-C to stop.")
    try:
        import time

        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\nstopping…")
        watcher.stop()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
) -> None:
    """Serve the web UI (open the printed URL in your browser)."""
    import uvicorn

    from .web.server import create_app

    cfg = load_config()
    console.print(f"[bold]filesearch web UI[/] → http://{host}:{port}")
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")


@app.command()
def gui() -> None:
    """Open the native desktop search window."""
    from .desktop import run_desktop

    run_desktop(load_config())


if __name__ == "__main__":
    app()
