"""YAML schema for Knowledge Base entries — templates, tips, and tricks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ruamel.yaml import YAML


class EntryType(str, Enum):
    TEMPLATE = "template"
    TIP = "tip"
    TRICK = "trick"


@dataclass
class KBEntry:
    """Base knowledge base entry."""

    name: str
    entry_type: EntryType
    description: str
    tags: list[str] = field(default_factory=list)
    build_systems: list[str] = field(default_factory=list)
    times_used: int = 0
    success_rate: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.entry_type.value,
            "description": self.description,
            "tags": self.tags,
            "build_systems": self.build_systems,
            "times_used": self.times_used,
            "success_rate": round(self.success_rate, 2),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TemplateEntry(KBEntry):
    """A complete, successful Containerfile indexed by characteristics."""

    containerfile: str = ""
    coordinate: str = ""
    l4_score: float = 0.0

    def __post_init__(self):
        self.entry_type = EntryType.TEMPLATE

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["containerfile"] = self.containerfile
        d["coordinate"] = self.coordinate
        d["l4_score"] = round(self.l4_score, 4)
        return d


@dataclass
class TipEntry(KBEntry):
    """A technique with trigger condition, solution, and caveats."""

    trigger: str = ""
    solution: str = ""
    caveats: str = ""

    def __post_init__(self):
        self.entry_type = EntryType.TIP

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["trigger"] = self.trigger
        d["solution"] = self.solution
        d["caveats"] = self.caveats
        return d


@dataclass
class TrickEntry(KBEntry):
    """A specific error→fix mapping."""

    error_pattern: str = ""
    fix: str = ""
    example_log: str = ""

    def __post_init__(self):
        self.entry_type = EntryType.TRICK

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["error_pattern"] = self.error_pattern
        d["fix"] = self.fix
        d["example_log"] = self.example_log
        return d


_yaml = YAML()
_yaml.default_flow_style = False


def save_entry(entry: KBEntry, kb_dir: Path) -> Path:
    """Save a KB entry to a YAML file."""
    kb_dir.mkdir(parents=True, exist_ok=True)
    path = kb_dir / f"{entry.name}.yaml"
    entry.updated_at = time.time()
    _yaml.dump(entry.to_dict(), path)
    return path


def load_entry(path: Path) -> KBEntry | None:
    """Load a KB entry from a YAML file."""
    if not path.exists():
        return None
    data = _yaml.load(path)
    if not data:
        return None

    entry_type = EntryType(data.get("type", "tip"))
    common = dict(
        name=data.get("name", path.stem),
        entry_type=entry_type,
        description=data.get("description", ""),
        tags=data.get("tags", []),
        build_systems=data.get("build_systems", []),
        times_used=data.get("times_used", 0),
        success_rate=data.get("success_rate", 0.0),
        created_at=data.get("created_at", 0),
        updated_at=data.get("updated_at", 0),
    )

    if entry_type == EntryType.TEMPLATE:
        return TemplateEntry(
            **common,
            containerfile=data.get("containerfile", ""),
            coordinate=data.get("coordinate", ""),
            l4_score=data.get("l4_score", 0.0),
        )
    elif entry_type == EntryType.TIP:
        return TipEntry(
            **common,
            trigger=data.get("trigger", ""),
            solution=data.get("solution", ""),
            caveats=data.get("caveats", ""),
        )
    elif entry_type == EntryType.TRICK:
        return TrickEntry(
            **common,
            error_pattern=data.get("error_pattern", ""),
            fix=data.get("fix", ""),
            example_log=data.get("example_log", ""),
        )
    return None


def load_all_entries(kb_dir: Path) -> list[KBEntry]:
    """Load all KB entries from a directory."""
    if not kb_dir.exists():
        return []
    entries = []
    for path in sorted(kb_dir.glob("*.yaml")):
        entry = load_entry(path)
        if entry:
            entries.append(entry)
    return entries
