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
import structlog
from dockerfile_parse import DockerfileParser

from buildroot.agent.analyzer import sanitize_gha_expressions
from buildroot.agent.models import EvalResult
from buildroot.pipeline.orchestrator import parse_gav
from buildroot.utils.jar_comparator import compare_jars
from buildroot.utils.maven_central import MAVEN_CENTRAL_BASE
from buildroot.utils import pypi_client
from buildroot.utils.sdist_comparator import compare_sdists, compare_wheels

logger = logging.getLogger(__name__)
pylogger = structlog.get_logger(__name__)


class Evaluator:
    """Runs 4-level evaluation: parse, build, command, JAR match."""

    def __init__(self, host: str = "rh-h100-01", timeout: int = 900) -> None:
        self._host = host
        self._timeout = timeout

    def evaluate(
        self,
        containerfile: str,
        coordinate: str,
        capture_full_log: bool = False,
    ) -> EvalResult:
        containerfile = sanitize_gha_expressions(containerfile)
        result = EvalResult()

        if not self._l1_parse(containerfile, result):
            result.compute_reward()
            return result

        tag = f"buildroot-agent-{uuid.uuid4().hex[:8]}"

        if not self._l2_build(containerfile, tag, result, capture_full_log):
            self._cleanup_image(tag)
            result.compute_reward()
            return result

        if not self._l3_command(tag, result):
            self._cleanup_image(tag)
            result.compute_reward()
            return result

        from buildroot.eval.test_runner import run_tests
        result.test_result = run_tests(tag, self._host, containerfile, timeout=300)

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

    def _l2_build(self, containerfile: str, tag: str, result: EvalResult, capture_full_log: bool = False) -> bool:
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
            if capture_full_log:
                result.build_log = build_log
            else:
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
                result.comparison_report = report
                result.comparison_verdict = report.verdict
                result.l4_score = report.equivalence_score()
                if report.verdict in ("IDENTICAL", "EQUIVALENT"):
                    result.l4_match = True
                else:
                    parts = [
                        f"verdict={report.verdict}",
                        f"structural_match={report.structural.match}",
                        f"metadata_match={report.metadata.match}",
                        f"bytecode_match={report.bytecode.match}",
                    ]
                    if not report.structural.match and hasattr(report.structural, 'diff'):
                        diff = report.structural.diff
                        if hasattr(diff, 'missing') and diff.missing:
                            parts.append(f"missing_files={diff.missing[:5]}")
                        if hasattr(diff, 'extra') and diff.extra:
                            parts.append(f"extra_files={diff.extra[:5]}")
                    if not report.metadata.match:
                        if hasattr(report.metadata, 'manifest_diff_keys') and report.metadata.manifest_diff_keys:
                            parts.append(f"metadata_diffs={report.metadata.manifest_diff_keys[:5]}")
                    if not report.bytecode.match:
                        if hasattr(report.bytecode, 'classes_divergent') and report.bytecode.classes_divergent:
                            parts.append(f"bytecode_diffs={report.bytecode.classes_divergent[:5]}")
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

    def l4_fallback_signals(
        self, tag: str, coordinate: str, jdk_version: str = "",
    ) -> dict:
        """Compute fallback L4 signals when no original JAR is available.

        Returns dict with bytecode_version_match, manifest_sanity keys.
        """
        from buildroot.agent.scorer import check_bytecode_version_match, check_manifest_sanity

        group_id, artifact_id, version = parse_gav(coordinate)
        signals: dict = {}

        try:
            with tempfile.TemporaryDirectory(prefix="buildroot-fb-") as tmpdir:
                rebuilt_jar = self._extract_rebuilt_jar(tag, artifact_id, version, Path(tmpdir))
                if rebuilt_jar:
                    if jdk_version:
                        signals["bytecode_version_match"] = check_bytecode_version_match(
                            rebuilt_jar, jdk_version,
                        )
                    signals["manifest_sanity"] = check_manifest_sanity(
                        rebuilt_jar, group_id, artifact_id,
                    )
        except Exception as e:
            logger.warning("Fallback signal extraction failed: %s", e)

        return signals

    # ------------------------------------------------------------------
    # Python-specific evaluation pipeline
    # ------------------------------------------------------------------

    def evaluate_python(
        self,
        containerfile: str,
        coordinate: str,
        capture_full_log: bool = False,
    ) -> EvalResult:
        """Python-specific evaluation pipeline.

        ``coordinate`` format: ``'package==version'``
        (e.g., ``'requests==2.31.0'``).

        L1: _l1_parse  (REUSE existing -- ecosystem agnostic)
        L2: _l2_build  (REUSE existing -- ecosystem agnostic)
        L3: _l3_python_command (NEW -- find sdist/wheel)
        L4: _l4_python_match   (NEW -- compare against PyPI)
        """
        containerfile = sanitize_gha_expressions(containerfile)
        result = EvalResult()
        tag = f"buildroot-py-{coordinate.replace('==', '-').replace('.', '-')[:40]}"

        # L1: Parse Containerfile (reuse)
        if not self._l1_parse(containerfile, result):
            result.compute_reward()
            return result

        # L2: Build container (reuse)
        if not self._l2_build(containerfile, tag, result, capture_full_log):
            self._cleanup_image(tag)
            result.compute_reward()
            return result

        # L3: Find Python artifact
        if not self._l3_python_command(tag, result):
            self._cleanup_image(tag)
            result.compute_reward()
            return result

        # L4: Compare against PyPI original
        self._l4_python_match(tag, coordinate, result)
        self._cleanup_image(tag)
        result.compute_reward()
        return result

    def _l3_python_command(self, tag: str, result: EvalResult) -> bool:
        """Find sdist (.tar.gz) or wheel (.whl) in the container.

        Searches ``/build/dist`` first, then ``*/dist/`` up to depth 4.
        On success sets ``result.l3_command = True`` and appends the
        ``ARTIFACT_PATH=...`` line to ``result.build_log`` so that
        ``_l4_python_match`` can extract it.
        """
        try:
            check_cmd = (
                f"podman run --rm {tag} sh -c '"
                f"found=$(find /build/dist -name \"*.tar.gz\" -o -name \"*.whl\" 2>/dev/null | head -1); "
                f"if [ -z \"$found\" ]; then "
                f"  found=$(find / -maxdepth 4 \\( -path \"*/dist/*.tar.gz\" -o -path \"*/dist/*.whl\" \\) 2>/dev/null | head -1); "
                f"fi; "
                f"if [ -n \"$found\" ]; then "
                f"  echo \"BUILD_SUCCESS\"; "
                f"  echo \"ARTIFACT_PATH=$found\"; "
                f"else "
                f"  echo \"BUILD_FAILED: no sdist or wheel found in dist/\"; "
                f"fi'"
            )
            proc = subprocess.run(
                [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=no",
                    self._host, check_cmd,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = proc.stdout + proc.stderr
            result.build_log += "\n--- L3 python check ---\n" + output[-2000:]

            if "BUILD_SUCCESS" in output and proc.returncode == 0:
                result.l3_command = True
                pylogger.info(
                    "L3 python artifact found",
                    tag=tag,
                    output=output.strip()[:200],
                )
                return True
            else:
                result.error_summary = _extract_error_lines(output)
                pylogger.warning(
                    "L3 python artifact not found",
                    tag=tag,
                    output=output.strip()[:200],
                )
                return False
        except subprocess.TimeoutExpired:
            result.error_summary = "L3 python command check timed out"
            return False
        except Exception as e:
            result.error_summary = f"L3 python command error: {e}"
            return False

    def _l4_python_match(
        self, tag: str, coordinate: str, result: EvalResult
    ) -> None:
        """Compare rebuilt artifact against PyPI original.

        1. Parse coordinate: ``'requests==2.31.0'`` -> ``('requests', '2.31.0')``
        2. Extract ``ARTIFACT_PATH`` from ``result.build_log``
        3. Download original sdist/wheel from PyPI
        4. Extract rebuilt artifact from container via podman
        5. Run ``compare_sdists`` or ``compare_wheels``
        6. Populate ``result.l4_match``, ``result.l4_score``,
           ``result.comparison_verdict``, ``result.diff_summary``
        """
        package, version = self._parse_python_coordinate(coordinate)

        # Find the artifact path recorded by _l3_python_command
        artifact_path = self._extract_artifact_path(result.build_log)
        if not artifact_path:
            result.error_summary = (
                "L4: could not determine artifact path from L3 output"
            )
            pylogger.warning("L4 python: no ARTIFACT_PATH in build_log")
            return

        is_wheel = artifact_path.endswith(".whl")

        try:
            with tempfile.TemporaryDirectory(prefix="buildroot-py-l4-") as tmpdir:
                tmp = Path(tmpdir)

                # Download original from PyPI
                original_path = self._download_python_original(
                    package, version, tmp, is_wheel=is_wheel
                )
                if not original_path:
                    result.error_summary = (
                        f"L4: could not download original "
                        f"{'wheel' if is_wheel else 'sdist'} from PyPI"
                    )
                    return

                # Extract rebuilt artifact from container
                rebuilt_path = self._extract_python_artifact(
                    tag, artifact_path, tmp
                )
                if not rebuilt_path:
                    result.error_summary = (
                        "L4: could not extract rebuilt artifact from container"
                    )
                    return

                # Compare
                if is_wheel:
                    report = compare_wheels(
                        original_path, rebuilt_path, coordinate
                    )
                else:
                    report = compare_sdists(
                        original_path, rebuilt_path, coordinate
                    )

                result.comparison_report = report
                result.comparison_verdict = report.verdict
                result.l4_score = report.equivalence_score()

                if report.verdict in ("IDENTICAL", "EQUIVALENT"):
                    result.l4_match = True
                    pylogger.info(
                        "L4 python match",
                        coordinate=coordinate,
                        verdict=report.verdict,
                        score=result.l4_score,
                    )
                else:
                    parts = [
                        f"verdict={report.verdict}",
                        f"structural_match={report.structural.match}",
                    ]
                    if not report.structural.match:
                        diff = report.structural.diff
                        if diff.missing:
                            parts.append(
                                f"missing_files={diff.missing[:5]}"
                            )
                        if diff.extra:
                            parts.append(f"extra_files={diff.extra[:5]}")
                    if hasattr(report, "source") and not report.source.match:
                        parts.append(
                            f"source_diffs={report.source.files_divergent[:5]}"
                        )
                    if hasattr(report, "metadata") and not report.metadata.match:
                        parts.append(
                            f"metadata_diffs={report.metadata.metadata_diff_fields[:5]}"
                        )
                    result.diff_summary = ", ".join(parts)
                    pylogger.info(
                        "L4 python divergent",
                        coordinate=coordinate,
                        diff_summary=result.diff_summary,
                    )

        except Exception as e:
            result.error_summary = f"L4 python comparison error: {e}"
            pylogger.exception("L4 python comparison failed", coordinate=coordinate)

    def _parse_python_coordinate(self, coordinate: str) -> tuple[str, str]:
        """Parse ``'package==version'`` into ``(package, version)``.

        Also accepts ``'package=version'`` and ``'package:version'``
        for flexibility.
        """
        for sep in ("==", "=", ":"):
            if sep in coordinate:
                parts = coordinate.split(sep, 1)
                return parts[0].strip(), parts[1].strip()
        raise ValueError(
            f"Cannot parse Python coordinate: {coordinate!r}. "
            f"Expected format: 'package==version'"
        )

    def _extract_artifact_path(self, build_log: str) -> str | None:
        """Extract ``ARTIFACT_PATH=<path>`` from build log output."""
        match = re.search(r"ARTIFACT_PATH=(.+)", build_log)
        if match:
            return match.group(1).strip()
        return None

    def _download_python_original(
        self,
        package: str,
        version: str,
        dest: Path,
        *,
        is_wheel: bool = False,
    ) -> Path | None:
        """Download the original sdist or wheel from PyPI."""
        try:
            if is_wheel:
                dest_path = dest / f"{package}-{version}-original.whl"
                return pypi_client.download_wheel(
                    package, version, dest_path, verify_checksum=True
                )
            else:
                dest_path = dest / f"{package}-{version}-original.tar.gz"
                return pypi_client.download_sdist(
                    package, version, dest_path, verify_checksum=True
                )
        except (requests.RequestException, ValueError) as e:
            pylogger.warning(
                "Could not download original Python artifact",
                package=package,
                version=version,
                error=str(e),
            )
            return None

    def _extract_python_artifact(
        self, tag: str, artifact_path: str, dest: Path
    ) -> Path | None:
        """Extract a rebuilt Python artifact from the container via podman."""
        try:
            filename = Path(artifact_path).name
            local_path = dest / f"rebuilt-{filename}"
            copy_cmd = (
                f"podman run --rm {tag} cat {shlex.quote(artifact_path)}"
            )
            proc = subprocess.run(
                [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=no",
                    self._host, copy_cmd,
                ],
                capture_output=True,
                timeout=120,
            )
            if proc.returncode == 0 and proc.stdout:
                local_path.write_bytes(proc.stdout)
                return local_path
            pylogger.warning(
                "Failed to extract python artifact",
                tag=tag,
                artifact_path=artifact_path,
                returncode=proc.returncode,
            )
            return None
        except Exception as e:
            pylogger.warning(
                "Could not extract rebuilt Python artifact",
                error=str(e),
            )
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
