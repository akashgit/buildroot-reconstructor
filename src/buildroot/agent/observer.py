"""Observer agent — wraps existing reconstruct() to produce initial BuildrootSpec + Containerfile."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from buildroot.pipeline.models import BuildrootSpec
from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav

logger = logging.getLogger(__name__)


def detect_build_system(source_repo: str, git_tag: str) -> str:
    """Detect the build system by checking for marker files in the repo.

    Returns 'gradle', 'ant', or 'maven' (default).
    """
    if not source_repo or not git_tag:
        return "maven"

    try:
        check_files = ["build.gradle", "build.gradle.kts", "gradlew", "build.xml"]
        for filename in check_files:
            check = subprocess.run(
                ["git", "archive", "--remote", source_repo, git_tag, "--", filename],
                capture_output=True, timeout=15,
            )
            if check.returncode == 0 and check.stdout:
                if filename in ("build.gradle", "build.gradle.kts", "gradlew"):
                    logger.info("Detected Gradle build system via %s", filename)
                    return "gradle"
                if filename == "build.xml":
                    logger.info("Detected Ant build system via %s", filename)
                    return "ant"
    except Exception as e:
        logger.debug("Build system detection failed: %s", e)

    return "maven"


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

            if spec.source_repo and spec.git_tag and not spec.build_commands:
                build_sys = detect_build_system(spec.source_repo, spec.git_tag)
                if build_sys == "gradle":
                    spec.build_commands = ["./gradlew build -x test"]
                    logger.info("Auto-detected Gradle; set build command")
                elif build_sys == "ant":
                    spec.build_commands = ["ant jar"]
                    logger.info("Auto-detected Ant; set build command")

            containerfile_path = Path(tmpdir) / "Containerfile"
            if containerfile_path.exists():
                containerfile = containerfile_path.read_text()
            else:
                logger.warning("No Containerfile generated for %s", coordinate)
                containerfile = ""
        return spec, containerfile
