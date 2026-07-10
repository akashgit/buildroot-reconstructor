"""Typed utilities for verifying CVE NV-001052 patch artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def check_disconnect_restored(path: Path) -> bool:
    """Check if the disconnect() call is present in a Containerfile or source file."""
    content = path.read_text(encoding="utf-8")
    has_disconnect_comment = "Eagerly disconnect the Session here" in content
    has_disconnect_call = "getCurrentSession().disconnect()" in content
    return has_disconnect_comment or has_disconnect_call


def analyze_containerfile(path: Path) -> dict[str, Any]:
    """Analyze a Containerfile and return structural metadata."""
    content = path.read_text(encoding="utf-8")
    lines = content.strip().splitlines()

    directives: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Z]+)\s", stripped)
        if match:
            directive = match.group(1)
            directives[directive] = directives.get(directive, 0) + 1

    return {
        "total_lines": len(lines),
        "directives": directives,
        "has_from": "FROM" in directives,
        "has_run": "RUN" in directives,
        "has_workdir": "WORKDIR" in directives,
        "has_copy": "COPY" in directives,
        "has_env": "ENV" in directives,
        "patched_files": extract_patched_files(content),
    }


def extract_patched_files(content: str) -> list[str]:
    """Extract Java file names referenced in sed/patch commands."""
    pattern = r"sed\s+-i\s+.*?(\w+\.java)"
    matches = re.findall(pattern, content)
    return sorted(set(matches))


def load_containerfile_from_intake(intake_path: Path) -> str:
    """Load the Containerfile content from the intake JSON."""
    data = json.loads(intake_path.read_text(encoding="utf-8"))
    containerfile: str = data["containerfile"]
    return containerfile
