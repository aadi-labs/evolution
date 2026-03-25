"""Notes hub — file-based storage for agent notes."""
from __future__ import annotations

import re
import threading
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
        self._lock = threading.Lock()
        self._next_id_counter = self._compute_next_id()

    def _compute_next_id(self) -> int:
        ids = []
        for f in self.path.glob("*.md"):
            match = re.match(r"(\d+)-", f.name)
            if match:
                ids.append(int(match.group(1)))
        return max(ids, default=0) + 1

    def add(self, agent: str, text: str, tags: list[str] | None = None) -> Note:
        """Add a new note and write it to a markdown file."""
        with self._lock:
            note_id = self._next_id_counter
            self._next_id_counter += 1
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
        """Read all note files, optionally filtered by agent.

        Notes are sorted by frontmatter timestamp (earliest first),
        falling back to file mtime when timestamp is empty.
        """
        notes: list[tuple[Note, Path]] = []
        for f in self.path.glob("*.md"):
            note = self._read(f)
            if note is not None:
                if agent is None or note.agent == agent:
                    notes.append((note, f))

        notes.sort(key=lambda pair: pair[0].timestamp or datetime.fromtimestamp(pair[1].stat().st_mtime, tz=timezone.utc).isoformat())
        return [n for n, _ in notes]

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
