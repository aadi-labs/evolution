"""Notes hub — file-based storage for agent notes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Note:
    agent: str
    text: str
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""


class NotesHub:
    """Manages notes stored as markdown files with YAML frontmatter."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def _compute_next_id(self) -> int:
        ids = []
        for f in self.path.glob("*.md"):
            match = re.match(r"(\d+)-", f.name)
            if match:
                ids.append(int(match.group(1)))
        return max(ids, default=0) + 1

    def add(self, agent: str, text: str, tags: list[str] | None = None) -> Note:
        """Add a new note and write it to a markdown file."""
        note_id = self._compute_next_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        note = Note(
            agent=agent,
            text=text,
            tags=tags or [],
            timestamp=timestamp,
        )

        frontmatter: dict[str, Any] = {
            "agent": note.agent,
            "tags": note.tags,
            "timestamp": note.timestamp,
        }

        body = note.text
        content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n" + body + "\n"

        filename = f"{note_id:03d}-{agent}.md"
        (self.path / filename).write_text(content)

        return note

    def list(self, agent: str | None = None) -> list[Note]:
        """Read all note files, optionally filtered by agent."""
        notes = []
        for f in sorted(self.path.glob("*.md")):
            note = self._read(f)
            if note is not None:
                if agent is None or note.agent == agent:
                    notes.append(note)
        return notes

    def _read(self, filepath: Path) -> Note | None:
        """Parse a markdown note file with YAML frontmatter."""
        text = filepath.read_text()
        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        fm = yaml.safe_load(parts[1])
        if fm is None:
            return None

        body = parts[2].strip()

        return Note(
            agent=fm.get("agent", ""),
            text=body,
            tags=fm.get("tags", []),
            timestamp=fm.get("timestamp", ""),
        )
