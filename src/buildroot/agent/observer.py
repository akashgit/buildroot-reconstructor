"""Observer agent — wraps existing reconstruct() to produce initial BuildrootSpec + Containerfile."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from buildroot.pipeline.models import BuildrootSpec
from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav

logger = logging.getLogger(__name__)


class Observer:
    """Delegates to the existing one-shot pipeline to produce an initial Containerfile."""

    def __init__(self, *, skip_deps: bool = False) -> None:
        self._orchestrator = BuildrootOrchestrator(skip_deps=skip_deps)

    def observe(self, coordinate: str) -> tuple[BuildrootSpec, str]:
        group_id, artifact_id, version = parse_gav(coordinate)
        with tempfile.TemporaryDirectory(prefix="buildroot-observe-") as tmpdir:
            spec = self._orchestrator.reconstruct(
                group_id, artifact_id, version, output_dir=tmpdir
            )
            containerfile_path = Path(tmpdir) / "Containerfile"
            if containerfile_path.exists():
                containerfile = containerfile_path.read_text()
            else:
                logger.warning("No Containerfile generated for %s", coordinate)
                containerfile = ""
        return spec, containerfile
