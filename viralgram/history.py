"""게시 이력 (중복 게시 방지)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

MAX_ENTRIES = 1000


class History:
    def __init__(self, path: Path):
        self.path = path
        self.entries: list[dict] = []
        if path.exists():
            self.entries = json.loads(path.read_text(encoding="utf-8"))

    @property
    def ids(self) -> set[str]:
        return {e["id"] for e in self.entries}

    def recent_titles(self, n: int = 30) -> list[str]:
        return [e["title"] for e in self.entries[-n:]]

    def add(self, story_id: str, title: str, link: str, media_id: str | None) -> None:
        self.entries.append(
            {
                "id": story_id,
                "title": title,
                "link": link,
                "media_id": media_id,
                "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        self.entries = self.entries[-MAX_ENTRIES:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
