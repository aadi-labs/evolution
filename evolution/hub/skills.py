"""Skills hub — file-based storage for reusable agent skills."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Skill:
    author: str
    name: str
    content: str
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""


class SkillsHub:
    """Manages skills stored as markdown files with YAML frontmatter."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def add(self, author: str, name: str, content: str, tags: list[str] | None = None) -> Skill:
        """Add a new skill and write it to a markdown file."""
        timestamp = datetime.now(timezone.utc).isoformat()

        skill = Skill(
            author=author,
            name=name,
            content=content,
            tags=tags or [],
            timestamp=timestamp,
        )

        frontmatter: dict[str, Any] = {
            "author": skill.author,
            "name": skill.name,
            "tags": skill.tags,
            "timestamp": skill.timestamp,
        }

        body = skill.content
        file_content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n" + body + "\n"

        filename = f"{name}.md"
        (self.path / filename).write_text(file_content)

        return skill

    def list(self) -> list[Skill]:
        """Read all skill files, sorted by filename."""
        skills = []
        for f in sorted(self.path.glob("*.md")):
            skill = self._read(f)
            if skill is not None:
                skills.append(skill)
        return skills

    def _read(self, filepath: Path) -> Skill | None:
        """Parse a markdown skill file with YAML frontmatter."""
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

        return Skill(
            author=fm.get("author", ""),
            name=fm.get("name", ""),
            content=body,
            tags=fm.get("tags", []),
            timestamp=fm.get("timestamp", ""),
        )
