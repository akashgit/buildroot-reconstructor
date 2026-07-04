"""Seed the builds table from existing KB entries and batch results."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def seed_from_kb(kb_dir: Path) -> int:
    """Seed from ~/.buildroot/kb/*.yaml template entries."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed — skipping KB seed")
        return 0

    from buildroot.agent.build_store import save_build

    count = 0
    for f in sorted(kb_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text())
        except Exception:
            continue
        coord = data.get("coordinate", "")
        cf = data.get("containerfile", "")
        score = data.get("l4_score", 0)
        if coord and cf and score > 0:
            if save_build(coord, cf, score, 4, "kb-seed"):
                count += 1
    return count


def seed_from_results(results_dir: Path) -> int:
    """Seed from batch results directory (attempts.json + Containerfile.best)."""
    from buildroot.agent.build_store import save_build

    count = 0
    for pkg_dir in sorted(results_dir.iterdir()):
        if not pkg_dir.is_dir():
            continue
        att = pkg_dir / "attempts.json"
        cf = pkg_dir / "Containerfile.best"
        if not att.exists():
            continue
        try:
            data = json.loads(att.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        coord = data.get("coordinate", "")
        reward = data.get("best_reward", 0)
        status = data.get("status", "")
        method = data.get("method", "")
        if status != "success" or reward < 0.98:
            continue
        containerfile = cf.read_text() if cf.exists() else ""
        if not containerfile:
            continue
        if save_build(coord, containerfile, reward, 4, method):
            count += 1
    return count


def main():
    kb_dir = Path.home() / ".buildroot" / "kb"
    results_dir = Path("/workspace/shiv/results/unpatched-batch")

    total = 0
    if kb_dir.exists():
        n = seed_from_kb(kb_dir)
        logger.info("Seeded %d builds from KB (%s)", n, kb_dir)
        total += n

    if results_dir.exists():
        n = seed_from_results(results_dir)
        logger.info("Seeded %d builds from results (%s)", n, results_dir)
        total += n

    logger.info("Total: %d builds seeded", total)


if __name__ == "__main__":
    main()
