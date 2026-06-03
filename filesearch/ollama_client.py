"""Thin wrapper over the local Ollama server for the three things we need:
tag text, caption images (vision model), and embed text (semantic search).

All model output for tagging is requested as JSON and parsed leniently, so a
malformed response degrades to a best-effort ``TagResult`` rather than crashing
the indexer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from ollama import Client

from .models import TagResult

_TAG_SYSTEM = (
    "You are a file-indexing assistant. Read the file content and return ONLY a "
    "JSON object describing it, with these keys:\n"
    '  "summary": one or two sentence plain-language summary,\n'
    '  "tags": 3-8 short lowercase topical keywords (array of strings),\n'
    '  "category": a single word such as document, code, spreadsheet, '
    "presentation, image, data, config, note, email, finance, legal, or other,\n"
    '  "entities": notable names, organizations, products, or dates (array, may be empty),\n'
    '  "language": the natural or programming language of the file.\n'
    "Do not include any text outside the JSON object."
)

_VISION_PROMPT = (
    "Describe this image for a file search index. Return ONLY a JSON object with keys: "
    '"summary" (one sentence describing the image), '
    '"tags" (3-8 lowercase keywords for what is visible), '
    '"category" (always "image"), '
    '"entities" (any readable text, names, or recognizable objects/places; may be empty), '
    '"language" (language of any text in the image, else "").'
)


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host
        self.client = Client(host=host)

    # --- availability ------------------------------------------------------
    def ping(self) -> bool:
        try:
            self.client.list()
            return True
        except Exception:
            return False

    def list_model_names(self) -> list[str]:
        res = self.client.list()
        models = res.get("models") if isinstance(res, dict) else getattr(res, "models", [])
        names: list[str] = []
        for m in models or []:
            if isinstance(m, dict):
                name = m.get("model") or m.get("name")
            else:
                name = getattr(m, "model", None) or getattr(m, "name", None)
            if name:
                names.append(name)
        return names

    def has_model(self, name: str) -> bool:
        if not name:
            return False
        base = name.split(":")[0]
        for n in self.list_model_names():
            if n == name or n.split(":")[0] == base:
                return True
        return False

    def pull(self, name: str, on_progress: Callable[[dict], None] | None = None) -> None:
        """Pull a model, invoking ``on_progress`` with each status dict."""
        for prog in self.client.pull(name, stream=True):
            if on_progress is None:
                continue
            if isinstance(prog, dict):
                on_progress(prog)
            else:  # ProgressResponse object in newer clients
                on_progress(
                    {
                        "status": getattr(prog, "status", ""),
                        "completed": getattr(prog, "completed", None),
                        "total": getattr(prog, "total", None),
                    }
                )

    # --- tagging -----------------------------------------------------------
    def tag_text(self, filename: str, content: str, model: str) -> TagResult:
        user = f"Filename: {filename}\n\nContent (may be truncated):\n{content}"
        try:
            resp = self.client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": _TAG_SYSTEM},
                    {"role": "user", "content": user},
                ],
                format="json",
                options={"temperature": 0, "num_predict": 512},
            )
            text = resp["message"]["content"] if isinstance(resp, dict) else resp.message.content
            return _parse_tag(text, fallback_summary=content)
        except Exception:
            return TagResult(summary=_head(content), tags=[], category="", entities=[], language="")

    def tag_image(self, image_path: str | Path, model: str) -> TagResult:
        try:
            data = Path(image_path).read_bytes()
            resp = self.client.generate(
                model=model,
                prompt=_VISION_PROMPT,
                images=[data],
                format="json",
                options={"temperature": 0, "num_predict": 512},
            )
            text = resp["response"] if isinstance(resp, dict) else resp.response
            tr = _parse_tag(text, fallback_summary="")
            if not tr.category:
                tr.category = "image"
            return tr
        except Exception:
            return TagResult(category="image")

    # --- embeddings --------------------------------------------------------
    def embed(self, text: str, model: str) -> np.ndarray | None:
        try:
            resp = self.client.embeddings(model=model, prompt=text)
            vec = resp["embedding"] if isinstance(resp, dict) else resp.embedding
            if not vec:
                return None
            return np.asarray(vec, dtype=np.float32)
        except Exception:
            return None


def _head(text: str, n: int = 200) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:n]


def _parse_tag(text: str, fallback_summary: str) -> TagResult:
    if not text:
        return TagResult(summary=_head(fallback_summary))
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return TagResult.from_model_json(data)
    except Exception:
        # Try to salvage the first {...} block.
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return TagResult.from_model_json(json.loads(text[start : end + 1]))
            except Exception:
                pass
    return TagResult(summary=_head(fallback_summary or text))
