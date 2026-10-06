"""Source collectors: each turns a Source row into RawItems (no AI, no DB writes)."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawItem:
    url: str
    title: str
    snippet: str = ""
    content_text: str | None = None  # set when the collector already has the full text
    published_at: datetime | None = None
    meta: dict = field(default_factory=dict)
