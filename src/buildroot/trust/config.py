"""Configuration loading for trusted source registry."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TRUST_CONFIG: dict = {
    "default_tier1_provider": "adoptium",
    "jdk_resolution_strategy": "nearest_lts_above",
    "dual_build": True,
    "sources": {
        "adoptium": {"tier": 1, "jdk_versions": ["8", "11", "17", "21", "25"]},
        "redhat_ubi": {"tier": 1, "jdk_versions": ["11", "17", "21", "25"]},
        "corretto": {"tier": 2, "jdk_versions": ["8", "11", "17", "21"]},
        "jdk_archive": {"tier": 3, "jdk_versions": ["9", "10", "12", "13", "14", "15", "16"]},
    },
}


def load_trust_config(
    factory_md_path: Path | None = None,
    override: dict | None = None,
) -> dict:
    """Load trusted source configuration.

    Priority: override dict > factory.md ## Trusted Sources > defaults.
    """
    config = dict(DEFAULT_TRUST_CONFIG)
    config["sources"] = dict(DEFAULT_TRUST_CONFIG["sources"])

    if factory_md_path and factory_md_path.exists():
        file_config = _parse_factory_md_trust_section(factory_md_path)
        if file_config:
            _merge_config(config, file_config)
            logger.info("Loaded trust config from %s", factory_md_path)

    if override:
        _merge_config(config, override)
        logger.info("Applied trust config override")

    return config


def _parse_factory_md_trust_section(path: Path) -> dict | None:
    text = path.read_text()
    marker = "## Trusted Sources"
    idx = text.find(marker)
    if idx == -1:
        return None

    section = text[idx + len(marker) :]
    end = section.find("\n## ")
    if end != -1:
        section = section[:end]

    config: dict = {}
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("- default_provider:"):
            config["default_tier1_provider"] = line.split(":", 1)[1].strip()
        elif line.startswith("- strategy:"):
            config["jdk_resolution_strategy"] = line.split(":", 1)[1].strip()
        elif line.startswith("- dual_build:"):
            val = line.split(":", 1)[1].strip().lower()
            config["dual_build"] = val in ("true", "yes", "1")

    return config if config else None


def _merge_config(base: dict, overlay: dict) -> None:
    for key, value in overlay.items():
        if key == "sources" and isinstance(value, dict):
            base.setdefault("sources", {}).update(value)
        else:
            base[key] = value
