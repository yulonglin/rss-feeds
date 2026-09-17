from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, Field


class Item(BaseModel):
    """One entry in a feed. `published` is always timezone-aware UTC."""

    title: str
    link: str
    guid: str
    published: datetime
    description: str = ""
    content_html: str | None = None
    author: str | None = None
    categories: list[str] = Field(default_factory=list)

    @staticmethod
    def at_midnight(d: date) -> datetime:
        """Date-only sources get a fixed time so output is byte-stable across runs."""
        return datetime(d.year, d.month, d.day, tzinfo=UTC)


class SourceResult(BaseModel):
    """What a source module returns: its items, or the reason it produced none."""

    items: list[Item] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.items)
