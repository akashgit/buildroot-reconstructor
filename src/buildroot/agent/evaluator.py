"""Evaluator agent — 4-level scoring with SSH-based remote builds."""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

import requests
from dockerfile_parse import DockerfileParser

from buildroot.agent.builder import sanitize_gha_expressions
from buildroot.agent.models import EvalResult
from buildroot.pipeline.orchestrator import parse_gav
from buildroot.utils.jar_comparator import compare_jars
from buildroot.utils.maven_central import MAVEN_CENTRAL_BASE

logger = logging.getLogger(__name__)


class Evaluator:
    """Runs 4-level evaluation: parse, build, command, JAR match."""

    def __init__(self, host: str = "rh-h100-01", timeout: int = 900) -> None:
        self._host = host
        self._timeout = timeout

    def evaluate(self, containerfile: str, coordinate: str) -> EvalResult:
        containerfile = sanitize_gha_expressions(containerfile)
        result = EvalResult()

        if not self._l1_parse(containerfile, result):
            result.compute_reward()
            return result

        tag = f"buildroot-agent-{uuid.uuid4().hex[:8]}"

        if not self._l2_build(containerfile, tag, result):
            self._cleanup_image(tag)
            result.compute_reward()
            return result

        if not self._l3_command(tag, result):
            self._cleanup_image(tag)
            result.compute_reward()
            return result

        self._l4_match(tag, coordinate, result)
        self._cleanup_image(tag)
        result.compute_reward()
        return result

    def _l1_parse(self, containerfile: str, result: EvalResult) -> bool:
        try:
            parser = DockerfileParser()
            parser.content = containerfile
            _ = parser.structure
            result.l1_parse = True
            return True
        except Exception as e:
            result.error_summary = f"L1 parse error: {e}"
            return False

    def _l2_build(self, containerfile: str, tag: str, result: EvalResult) -> bool:
        try:
            delimiter = f"CONTAINERFILE_EOF_{uuid.uuid4().hex[:8]}"
            safe_containerfile = containerfile.replace(delimiter, "")
            build_cmd = (
                f"cd $(mktemp -d) && "
                f"cat > Containerfile << '{delimiter}'\n{safe_containerfile}\n{delimiter}\n"
                f"podman build --no-cache -t {tag} -f Containerfile ."
            )
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                 self._host, build_cmd],
                capture_output=True, text=True, timeout=self._timeout,
            )
            build_log = proc.stdout + proc.stderr
            result.build_log = build_log[-5000:]

            if proc.returncode == 0:
                result.l2_build = True
                return True
            else:
                result.error_summary = _extract_error_lines(build_log)
                return False
        except subprocess.TimeoutExpired:
            result.error_summary = f"L2 build timed out after {self._timeout}s"
            return False
        except Exception as e:
            result.error_summary = f"L2 build error: {e}"
            return False

    def _l3_command(self, tag: str, result: EvalResult) -> bool:
        try:
            check_cmd = (
                f"podman run --rm {tag} sh -c '"
                f"find target/ build/libs/ */target/ */build/libs/ "
                f"-name \"*.jar\" "
                f"-not -name \"*-sources.jar\" "
                f"-not -name \"*-javadoc.jar\" "
                f"-not -name \"original-*.jar\" "
                f"2>/dev/null | head -1 | grep -q . "
                f"&& echo BUILD_SUCCESS || echo BUILD_FAILED'"
            )
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                 self._host, check_cmd],
                capture_output=True, text=True, timeout=120,
            )
            output = proc.stdout + proc.stderr
            result.build_log += "\n--- L3 check ---\n" + output[-2000:]

            if "BUILD_SUCCESS" in output and proc.returncode == 0:
                result.l3_command = True
                return True
            else:
                result.error_summary = _extract_error_lines(output)
                return False
        except subprocess.TimeoutExpired:
            result.error_summary = "L3 command check timed out"
            return False
        except Exception as e:
            result.error_summary = f"L3 command error: {e}"
            return False

    def _l4_match(self, tag: str, coordinate: str, result: EvalResult) -> None:
        group_id, artifact_id, version = parse_gav(coordinate)
        try:
            with tempfile.TemporaryDirectory(prefix="buildroot-l4-") as tmpdir:
                tmp = Path(tmpdir)
                original_jar = self._download_original_jar(
                    group_id, artifact_id, version, tmp
                )
                if not original_jar:
                    result.error_summary = "L4: could not download original JAR"
                    return

                rebuilt_jar = self._extract_rebuilt_jar(
                    tag, artifact_id, version, tmp
                )
                if not rebuilt_jar:
                    result.error_summary = "L4: could not extract rebuilt JAR from container"
                    return

                report = compare_jars(original_jar, rebuilt_jar, coordinate)
                result.comparison_verdict = report.verdict
                if report.verdict in ("IDENTICAL", "EQUIVALENT"):
                    result.l4_match = True
                else:
                    parts = [
                        f"verdict={report.verdict}",
                        f"structural_match={report.structural.match}",
                        f"metadata_match={report.metadata.match}",
                        f"bytecode_match={report.bytecode.match}",
                    ]
                    if not report.structural.match and hasattr(report.structural, 'details'):
                        details = report.structural.details
                        if hasattr(details, 'missing_files') and details.missing_files:
                            parts.append(f"missing_files={details.missing_files[:5]}")
                        if hasattr(details, 'extra_files') and details.extra_files:
                            parts.append(f"extra_files={details.extra_files[:5]}")
                    if not report.metadata.match and hasattr(report.metadata, 'details'):
                        details = report.metadata.details
                        if hasattr(details, 'differing_keys') and details.differing_keys:
                            parts.append(f"metadata_diffs={details.differing_keys[:5]}")
                    if not report.bytecode.match and hasattr(report.bytecode, 'details'):
                        details = report.bytecode.details
                        if hasattr(details, 'divergent_classes') and details.divergent_classes:
                            parts.append(f"bytecode_diffs={details.divergent_classes[:5]}")
                    result.diff_summary = ", ".join(parts)
        except Exception as e:
            result.error_summary = f"L4 comparison error: {e}"

    def _download_original_jar(
        self, group_id: str, artifact_id: str, version: str, dest: Path
    ) -> Path | None:
        group_path = group_id.replace(".", "/")
        jar_url = (
            f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/{version}/"
            f"{artifact_id}-{version}.jar"
        )
        try:
            resp = requests.get(jar_url, timeout=60)
            resp.raise_for_status()
            jar_path = dest / f"{artifact_id}-{version}-original.jar"
            jar_path.write_bytes(resp.content)
            return jar_path
        except requests.RequestException as e:
            logger.warning("Could not download original JAR: %s", e)
            return None

    def _extract_rebuilt_jar(
        self, tag: str, artifact_id: str, version: str, dest: Path
    ) -> Path | None:
        try:
            find_cmd = (
                f"podman run --rm {tag} sh -c "
                f"'find /build target -name \"*.jar\" -not -name \"*-sources.jar\" "
                f"-not -name \"*-javadoc.jar\" -not -name \"original-*.jar\" 2>/dev/null "
                f"| head -5'"
            )
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                 self._host, find_cmd],
                capture_output=True, text=True, timeout=60,
            )
            jar_paths = [
                line.strip() for line in proc.stdout.strip().splitlines()
                if line.strip().endswith(".jar")
            ]
            if not jar_paths:
                return None

            target_jar = None
            for jp in jar_paths:
                if artifact_id in jp and version in jp:
                    target_jar = jp
                    break
            if not target_jar:
                target_jar = jar_paths[0]

            local_jar = dest / f"{artifact_id}-{version}-rebuilt.jar"
            copy_cmd = (
                f"podman run --rm {tag} cat {shlex.quote(target_jar)}"
            )
            copy_proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                 self._host, copy_cmd],
                capture_output=True, timeout=120,
            )
            if copy_proc.returncode == 0 and copy_proc.stdout:
                local_jar.write_bytes(copy_proc.stdout)
                return local_jar
            return None
        except Exception as e:
            logger.warning("Could not extract rebuilt JAR: %s", e)
            return None

    def _cleanup_image(self, tag: str) -> None:
        try:
            subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                 self._host, f"podman rmi -f {tag} 2>/dev/null"],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass


def _extract_error_lines(log: str, max_lines: int = 15) -> str:
    """Extract the most informative error lines from a build log."""
    error_patterns = [
        re.compile(r"^\[ERROR\]", re.MULTILINE),
        re.compile(r"(?i)error:", re.MULTILINE),
        re.compile(r"(?i)fatal:", re.MULTILINE),
        re.compile(r"(?i)failed to", re.MULTILINE),
        re.compile(r"(?i)could not", re.MULTILINE),
        re.compile(r"(?i)cannot find", re.MULTILINE),
        re.compile(r"(?i)no such", re.MULTILINE),
    ]
    lines = log.splitlines()
    error_lines = []
    for i, line in enumerate(lines):
        for pat in error_patterns:
            if pat.search(line):
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                error_lines.extend(lines[start:end])
                break

    seen = set()
    deduped = []
    for line in error_lines:
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            deduped.append(stripped)
        if len(deduped) >= max_lines:
            break

    if not deduped:
        return "\n".join(lines[-max_lines:])
    return "\n".join(deduped)
