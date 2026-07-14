"""Level 2: Podman Build Verification — verify generated Containerfiles are buildable."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest
import requests

from buildroot.pipeline.orchestrator import BuildrootOrchestrator

TEST_PACKAGES = [
    pytest.param(
        "org.springframework.boot", "spring-boot", "2.7.18",
        id="spring-boot-2.7.18",
    ),
    pytest.param(
        "org.springframework.boot", "spring-boot-starter-web", "2.7.18",
        id="spring-boot-starter-web-2.7.18",
    ),
    pytest.param(
        "org.springframework", "spring-core", "5.3.31",
        id="spring-core-5.3.31",
    ),
    pytest.param(
        "org.springframework", "spring-context", "5.3.31",
        id="spring-context-5.3.31",
    ),
    pytest.param(
        "org.springframework.cloud", "spring-cloud-config-server", "3.1.8",
        id="spring-cloud-config-server-3.1.8",
    ),
    pytest.param(
        "org.springframework.security", "spring-security-core", "5.8.9",
        id="spring-security-core-5.8.9",
    ),
    pytest.param(
        "org.springframework.data", "spring-data-jpa", "2.7.18",
        id="spring-data-jpa-2.7.18",
    ),
    pytest.param(
        "org.thymeleaf", "thymeleaf-spring5", "3.0.15.RELEASE",
        id="thymeleaf-spring5-3.0.15.RELEASE",
    ),
    pytest.param(
        "io.micrometer", "micrometer-core", "1.10.13",
        id="micrometer-core-1.10.13",
    ),
    pytest.param(
        "org.apache.commons", "commons-lang3", "3.14.0",
        id="commons-lang3-3.14.0",
    ),
]

MINIMAL_POM_TEMPLATE = dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0"
             xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
             xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
                                 http://maven.apache.org/xsd/maven-4.0.0.xsd">
        <modelVersion>4.0.0</modelVersion>
        <groupId>{group_id}</groupId>
        <artifactId>{artifact_id}</artifactId>
        <version>{version}</version>
        <packaging>jar</packaging>
    </project>
""")


def _create_build_context(
    context_dir: Path,
    containerfile_content: str,
    group_id: str,
    artifact_id: str,
    version: str,
) -> Path:
    """Set up a minimal Maven project as build context for the Containerfile."""
    containerfile_path = context_dir / "Containerfile"
    containerfile_path.write_text(containerfile_content)

    pom_path = context_dir / "pom.xml"
    pom_path.write_text(MINIMAL_POM_TEMPLATE.format(
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
    ))

    src_dir = context_dir / "src" / "main" / "java"
    src_dir.mkdir(parents=True, exist_ok=True)

    return containerfile_path


def _strip_containerfile_to_setup(content: str) -> str:
    """Keep only FROM + package install + env setup lines, skip RUN mvn/build lines.

    We want to test that the container image is valid and packages install,
    not that the Maven build succeeds (that's Level 3).
    """
    lines = content.splitlines()
    result = []
    in_build_run = False

    for line in lines:
        stripped = line.strip()

        if in_build_run:
            if stripped.endswith("\\"):
                continue
            in_build_run = False
            continue

        lower = stripped.lower()

        is_build_command = (
            lower.startswith("run mvn ")
            or lower.startswith("run ./mvnw")
            or lower.startswith("run gradle ")
            or lower.startswith("run ./gradlew")
            or "apt-get" in lower
            or "microdnf" in lower
            or "dnf install" in lower
            or "yum install" in lower
            or "settings.xml" in lower
            or "git clone" in lower
            or "wget " in lower
            or "curl " in lower
        )

        if is_build_command:
            if stripped.endswith("\\"):
                in_build_run = True
            continue

        if lower.startswith("cmd ") or lower.startswith("entrypoint "):
            continue

        result.append(line)

    final = "\n".join(result).strip()
    if not final:
        return content

    return final + "\n"


@pytest.mark.integration
@pytest.mark.level2
@pytest.mark.slow
@pytest.mark.parametrize("group_id,artifact_id,version", TEST_PACKAGES)
class TestLevel2PodmanBuild:
    """Verify generated Containerfiles produce successful podman builds."""

    def test_podman_build(
        self, group_id, artifact_id, version, output_dir, podman_available
    ):
        try:
            orchestrator = BuildrootOrchestrator(skip_deps=True)
            orchestrator.reconstruct(
                group_id,
                artifact_id,
                version,
                output_dir=str(output_dir),
            )
        except requests.ConnectionError:
            pytest.skip("Maven Central unreachable")
        except requests.Timeout:
            pytest.skip("Maven Central request timed out")

        containerfile = output_dir / "Containerfile"
        assert containerfile.exists(), "Containerfile was not generated"

        from buildroot.agent.analyzer import sanitize_gha_expressions
        original_content = sanitize_gha_expressions(containerfile.read_text())
        setup_content = _strip_containerfile_to_setup(original_content)

        with tempfile.TemporaryDirectory(prefix="buildroot-l2-") as build_ctx:
            build_dir = Path(build_ctx)
            cf_path = _create_build_context(
                build_dir, setup_content, group_id, artifact_id, version
            )

            result = subprocess.run(
                [
                    "podman", "build",
                    "--no-cache",
                    "-f", str(cf_path),
                    str(build_dir),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )

            assert result.returncode == 0, (
                f"podman build failed for {group_id}:{artifact_id}:{version}\n"
                f"Exit code: {result.returncode}\n"
                f"Stderr (last 500 chars): {result.stderr[-500:]}\n"
                f"Containerfile:\n{setup_content}"
            )
