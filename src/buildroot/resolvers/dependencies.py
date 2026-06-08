"""Transitive dependency tree resolution via Maven."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from buildroot.pipeline.models import DependencyNode

logger = logging.getLogger(__name__)

TREE_LINE_RE = re.compile(
    r"\[INFO\]\s+"
    r"(?P<prefix>(?:[|+\\]\-?\s*)*)"
    r"(?P<gav>\S+:\S+:\S+:\S+:\S+)"
)

GAV_PREFIX_RE = re.compile(r"^[|+\\ \-]+")

TEMP_POM_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         http://maven.apache.org/xsd/maven-4.0.0.xsd"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.buildroot</groupId>
    <artifactId>temp-resolver</artifactId>
    <version>1.0</version>
    <dependencies>
        <dependency>
            <groupId>{group_id}</groupId>
            <artifactId>{artifact_id}</artifactId>
            <version>{version}</version>
        </dependency>
    </dependencies>
</project>
"""


class DependencyResolver:
    """Resolve transitive dependency trees by shelling out to Maven."""

    def resolve(
        self,
        group_id: str,
        artifact_id: str,
        version: str,
        *,
        skip_deps: bool = False,
    ) -> list[DependencyNode]:
        if skip_deps:
            return []

        mvn = self._find_maven()
        if not mvn:
            logger.warning(
                "Maven not found on PATH — skipping dependency resolution. "
                "Install Maven or add ./mvnw to the project."
            )
            return []

        tmp_dir = None
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="buildroot-deps-"))
            pom_path = self._create_temp_pom(
                group_id, artifact_id, version, tmp_dir
            )
            output = self._run_dependency_tree(mvn, pom_path)
            if output is None:
                return []
            return self._parse_tree_text(output)
        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _find_maven(self) -> str | None:
        mvn = shutil.which("mvn")
        if mvn:
            return mvn
        return None

    def _create_temp_pom(
        self,
        group_id: str,
        artifact_id: str,
        version: str,
        tmp_dir: Path,
    ) -> Path:
        pom_content = TEMP_POM_TEMPLATE.format(
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
        )
        pom_path = tmp_dir / "pom.xml"
        pom_path.write_text(pom_content, encoding="utf-8")
        return pom_path

    def _run_dependency_tree(self, mvn: str, pom_path: Path) -> str | None:
        cmd = [
            mvn,
            "dependency:tree",
            "-DoutputType=text",
            f"-f{pom_path}",
            "-B",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning(
                    "mvn dependency:tree failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:500] if result.stderr else "(no stderr)",
                )
                return None
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.warning("mvn dependency:tree timed out after 120s")
            return None
        except FileNotFoundError:
            logger.warning("Maven binary not found: %s", mvn)
            return None

    def _parse_tree_text(self, output: str) -> list[DependencyNode]:
        """Parse mvn dependency:tree text output into DependencyNode tree.

        The output looks like:
        [INFO] com.buildroot:temp-resolver:jar:1.0
        [INFO] +- org.springframework.boot:spring-boot:jar:2.7.18:compile
        [INFO] |  +- org.springframework:spring-core:jar:5.3.31:compile
        [INFO] |  \\- org.springframework:spring-context:jar:5.3.31:compile
        [INFO] \\- org.yaml:snakeyaml:jar:1.30:compile
        """
        lines = output.splitlines()
        dep_lines: list[tuple[int, DependencyNode]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("[INFO]"):
                continue

            after_info = stripped[len("[INFO]"):].strip()
            if not after_info:
                continue

            if after_info.startswith("---") or after_info.startswith("Building"):
                continue
            if after_info.startswith("Download") or after_info.startswith("Progress"):
                continue
            if after_info.startswith("Scanning") or after_info.startswith("None"):
                continue

            depth = self._compute_depth(after_info)
            node = self._parse_gav(after_info)
            if node:
                dep_lines.append((depth, node))

        if not dep_lines:
            return []

        # Skip the root project node (depth 0) — return its direct children as the tree
        root_nodes: list[DependencyNode] = []
        stack: list[tuple[int, DependencyNode]] = []

        start_idx = 0
        if dep_lines[0][0] == 0:
            start_idx = 1

        for depth, node in dep_lines[start_idx:]:
            while stack and stack[-1][0] >= depth:
                stack.pop()

            if stack:
                stack[-1][1].children.append(node)
            else:
                root_nodes.append(node)

            stack.append((depth, node))

        return root_nodes

    def _compute_depth(self, line: str) -> int:
        """Compute the depth from tree prefix characters."""
        match = GAV_PREFIX_RE.match(line)
        if not match:
            return 0
        prefix = match.group(0)
        depth = 0
        i = 0
        while i < len(prefix):
            ch = prefix[i]
            if ch in ("+", "\\"):
                depth += 1
                break
            elif ch == "|":
                depth += 1
                i += 3
            elif ch == " ":
                i += 1
            else:
                i += 1
        return depth

    def _parse_gav(self, line: str) -> DependencyNode | None:
        """Parse a GAV coordinate from a dependency tree line."""
        cleaned = GAV_PREFIX_RE.sub("", line).strip()
        if not cleaned:
            return None

        # Handle optional (scope) suffix like "(optional)"
        cleaned = re.sub(r"\s*\(.*\)\s*$", "", cleaned)

        parts = cleaned.split(":")
        if len(parts) < 4:
            return None

        if len(parts) == 5:
            return DependencyNode(
                group_id=parts[0],
                artifact_id=parts[1],
                version=parts[3],
                scope=parts[4],
            )
        elif len(parts) == 4:
            return DependencyNode(
                group_id=parts[0],
                artifact_id=parts[1],
                version=parts[3],
                scope="compile",
            )
        elif len(parts) >= 6:
            return DependencyNode(
                group_id=parts[0],
                artifact_id=parts[1],
                version=parts[3],
                scope=parts[4],
            )
        return None
