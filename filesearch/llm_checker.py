"""Wrapper around the ``llm-checker`` npm CLI.

``llm-checker recommend`` prints, per category (Coding / Reasoning /
Multimodal / ...), a block ending in ``Command: ollama pull <model>``. We run
it, strip ANSI, and pull out the model name for each category, then map them to
the roles this tool needs:

  * text model   -> tag documents & code   (Coding > Reasoning > General)
  * vision model -> caption images          (Multimodal)

Sensible fallbacks are used if ``llm-checker`` is unavailable or its output
can't be parsed; everything is overridable in config.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Real `recommend` output wraps everything in a box; lines look like:
#   "│ Coding (Coding):"  /  "│ Talking (Chat):"  /  "│ BEST OVERALL: model"
#   "│    Command: ollama pull <model>"
_BOX_PREFIX = "│╭╰╮╯─━┃|>•·*\t "
_CAT_PAREN = re.compile(r"^([A-Za-z][\w &/+-]*?)\s*\(([A-Za-z][\w &/+-]*)\):\s*$")
_CAT_PLAIN = re.compile(r"^([A-Za-z][\w &/+-]{1,30}):\s*$")
_BEST = re.compile(r"^BEST\s+OVERALL\s*:\s*([^\s|]+)", re.IGNORECASE)
_PULL = re.compile(r"ollama\s+pull\s+([^\s`'\"]+)")

# Used only when llm-checker can't be reached / parsed. Small + widely runnable.
FALLBACK_TEXT_MODEL = "llama3.2:3b"
FALLBACK_VISION_MODEL = "llama3.2-vision:11b"


def _run(args: list[str], timeout: int | None = 120) -> subprocess.CompletedProcess:
    """Run a command, routing npm-installed ``.cmd`` shims through cmd on Windows."""
    if os.name == "nt":
        args = ["cmd", "/c", *args]
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def is_installed() -> bool:
    """True if the ``llm-checker`` CLI is callable."""
    if not (shutil.which("llm-checker") or os.name == "nt"):
        return False
    try:
        cp = _run(["llm-checker", "--version"], timeout=60)
        return cp.returncode == 0
    except Exception:
        return False


def install() -> tuple[bool, str]:
    """Run ``npm install -g llm-checker``. Returns (ok, output)."""
    try:
        cp = _run(["npm", "install", "-g", "llm-checker"], timeout=600)
        return cp.returncode == 0, (cp.stdout + cp.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def recommend_raw(category: str | None = None) -> str:
    """Return the raw stdout (+stderr) of ``llm-checker recommend``."""
    args = ["llm-checker", "recommend"]
    if category:
        args += ["--category", category]
    cp = _run(args, timeout=300)
    return f"{cp.stdout}\n{cp.stderr}"


def parse_recommendations(text: str) -> dict[str, str]:
    """Map lowercased category name -> recommended model from recommend output.

    Handles the boxed output (lines prefixed with ``│``) and headers of the form
    ``Display (Canonical):`` (canonical name wins) as well as the plainer
    ``Coding:`` style. The ``BEST OVERALL`` model is stored under ``best``.
    """
    text = _ANSI.sub("", text)
    result: dict[str, str] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.lstrip(_BOX_PREFIX).rstrip()
        if not line:
            continue

        best = _BEST.match(line)
        if best:
            current = "best"
            result.setdefault("best", best.group(1))
            continue

        paren = _CAT_PAREN.match(line)
        if paren:
            current = paren.group(2).strip().lower()
            continue

        plain = _CAT_PLAIN.match(line)
        if plain and "pull" not in line.lower():
            current = plain.group(1).strip().lower()
            continue

        pull = _PULL.search(line)
        if pull:
            result.setdefault(current or "_loose", pull.group(1))
    return result


def choose_models(parsed: dict[str, str]) -> tuple[str | None, str | None]:
    """Pick (text_model, vision_model) from parsed category->model recommendations."""
    text_model = None
    for key in ("coding", "reasoning", "general", "chat", "instruct"):
        if key in parsed:
            text_model = parsed[key]
            break
    if text_model is None:
        for k, v in parsed.items():
            if "multimodal" not in k and "vision" not in k and k not in ("_loose", "best"):
                text_model = v
                break
    if text_model is None:
        text_model = parsed.get("best") or parsed.get("_loose")

    vision_model = None
    for k, v in parsed.items():
        if "multimodal" in k or "vision" in k:
            vision_model = v
            break

    return text_model, vision_model


def list_models_json(limit: int = 50) -> list:
    """Best-effort machine-readable model list (fallback discovery)."""
    try:
        cp = _run(["llm-checker", "list-models", "--json", "--limit", str(limit)])
        data = json.loads(cp.stdout)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("models", [])
    except Exception:
        pass
    return []


def discover_models() -> dict:
    """High-level: ensure installed, run recommend, return roles + raw output.

    Returns a dict: ``{installed, text_model, vision_model, parsed, raw}``.
    Never raises — falls back to defaults so ``setup`` can always proceed.
    """
    info: dict = {
        "installed": is_installed(),
        "text_model": None,
        "vision_model": None,
        "parsed": {},
        "raw": "",
        "used_fallback": False,
    }
    if not info["installed"]:
        info["text_model"] = FALLBACK_TEXT_MODEL
        info["vision_model"] = FALLBACK_VISION_MODEL
        info["used_fallback"] = True
        return info

    raw = recommend_raw()
    info["raw"] = raw
    parsed = parse_recommendations(raw)
    info["parsed"] = parsed
    text_model, vision_model = choose_models(parsed)

    if not text_model:
        text_model = FALLBACK_TEXT_MODEL
        info["used_fallback"] = True
    if not vision_model:
        vision_model = FALLBACK_VISION_MODEL

    info["text_model"] = text_model
    info["vision_model"] = vision_model
    return info
