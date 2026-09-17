from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from .models import Item


class FirstSeen:
    """Stamps undated entries with the date this tool first observed them.

    Some sources (OpenAI's misalignment Reports) publish no date at all. Using the
    current time each run would make every entry look new at every refresh. Instead the
    first run that sees a guid records today's date and commits it; later runs reuse it.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, str] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    def stamp(self, guid: str, *, today: date | None = None) -> datetime:
        if guid not in self._data:
            self._data[guid] = (today or datetime.now(UTC).date()).isoformat()
        return Item.at_midnight(date.fromisoformat(self._data[guid]))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(sorted(self._data.items())), indent=2) + "\n")
