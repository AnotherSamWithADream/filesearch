"""Pydantic schemas shared across the scanner, indexer, AI client, and search."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileMeta(BaseModel):
    """Filesystem metadata captured during a scan (no content yet)."""

    path: str
    name: str
    ext: str
    size: int
    mtime: float
    mime: str | None = None


class TagResult(BaseModel):
    """Structured tags/metadata produced by the on-device AI model.

    Parsed leniently from the model's JSON so that a malformed or partial
    response still yields a usable object instead of raising.
    """

    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    entities: list[str] = Field(default_factory=list)
    language: str = ""

    @classmethod
    def from_model_json(cls, data: dict) -> "TagResult":
        def as_list(v) -> list[str]:
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str):
                # Accept comma/semicolon separated strings too.
                return [p.strip() for p in v.replace(";", ",").split(",") if p.strip()]
            return []

        def as_str(v) -> str:
            if isinstance(v, str):
                return v.strip()
            if v is None:
                return ""
            return str(v)

        return cls(
            summary=as_str(data.get("summary")),
            tags=as_list(data.get("tags")),
            category=as_str(data.get("category")),
            entities=as_list(data.get("entities")),
            language=as_str(data.get("language")),
        )


class SearchHit(BaseModel):
    """A single ranked search result."""

    path: str
    name: str
    ext: str
    size: int
    mtime: float
    score: float
    match_type: str  # "keyword", "semantic", or "hybrid"
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    snippet: str = ""
