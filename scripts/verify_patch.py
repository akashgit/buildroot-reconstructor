"""Typed utilities for verifying CVE NV-001052 patch artifacts."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("scripts.verify_patch")

_json_formatter = logging.Formatter(
    json.dumps(
        {
            "time": "%(asctime)s",
            "name": "%(name)s",
            "level": "%(levelname)s",
            "message": "%(message)s",
        }
    )
)
_handler = logging.StreamHandler()
_handler.setFormatter(_json_formatter)
logger.addHandler(_handler)
logger.setLevel(logging.DEBUG)


def check_disconnect_restored(path: Path) -> bool:
    """Check if the disconnect() call is present in a Containerfile or source file."""
    logger.info("Checking disconnect() restoration in %s", path)
    content = path.read_text(encoding="utf-8")
    has_disconnect_comment = "Eagerly disconnect the Session here" in content
    has_disconnect_call = "getCurrentSession().disconnect()" in content
    result = has_disconnect_comment or has_disconnect_call
    logger.debug("disconnect check result: comment=%s call=%s", has_disconnect_comment, has_disconnect_call)
    return result


def analyze_containerfile(path: Path) -> dict[str, Any]:
    """Analyze a Containerfile and return structural metadata."""
    logger.info("Analyzing Containerfile at %s", path)
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

    logger.info("Found %d directives across %d lines", len(directives), len(lines))
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
    logger.debug("Extracting patched file references from content")
    pattern = r"sed\s+-i\s+.*?(\w+\.java)"
    matches = re.findall(pattern, content)
    logger.info("Found %d patched file references: %s", len(matches), sorted(set(matches)))
    return sorted(set(matches))


def load_containerfile_from_intake(intake_path: Path) -> str:
    """Load the Containerfile content from the intake JSON."""
    logger.info("Loading Containerfile from intake at %s", intake_path)
    data = json.loads(intake_path.read_text(encoding="utf-8"))
    containerfile: str = data["containerfile"]
    logger.debug("Loaded Containerfile: %d characters", len(containerfile))
    return containerfile
