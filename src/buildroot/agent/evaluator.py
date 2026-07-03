"""Evaluator agent — 4-level scoring via podman (local or remote via SSH)."""

from __future__ import annotations

import logging
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import requests
from dockerfile_parse import DockerfileParser

from buildroot.agent.analyzer import sanitize_gha_expressions
from buildroot.agent.models import EvalResult
from buildroot.pipeline.orchestrator import parse_gav
from buildroot.utils.jar_comparator import compare_jars
from buildroot.utils.maven_central import get_jar_path

TRUSTED_IMAGE_PATTERNS = [
    re.compile(r"^docker\.io/library/eclipse-temurin:\d+(\.\d+)*(_\d+)?-jdk"),
    re.compile(r"^registry\.access\.redhat\.com/ubi\d+/openjdk-\d+"),
]

logger = logging.getLogger(__name__)


class Evaluator:
    """Runs 4-level evaluation: parse, build, command, JAR match."""

    def __init__(self, host: str | None = None, timeout: int = 900, no_cache: bool = False) -> None:
        self._host = host
        self._timeout = timeout
        self._no_cache = no_cache

    def _run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a command locally, or via SSH if a host is configured."""
        if self._host:
            return subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                 self._host, shlex.join(cmd)],
                **kwargs,
            )
        return subprocess.run(cmd, **kwargs)

    def _run_shell(self, shell_cmd: str, **kwargs) -> subprocess.CompletedProcess:
        """Run a shell command string locally or via SSH."""
        if self._host:
            return subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                 self._host, shell_cmd],
                **kwargs,
            )
        return subprocess.run(shell_cmd, shell=True, **kwargs)

    def evaluate(
        self,
        containerfile: str,
        coordinate: str,
        capture_full_log: bool = False,
        *,
        trusted: bool = False,
    ) -> EvalResult:
        containerfile = sanitize_gha_expressions(containerfile)
        result = EvalResult()

        if not self._l1_parse(containerfile, result):
            result.compute_reward()
            return result

        if trusted and not self._l1_5_trust_check(containerfile, result):
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
        result.test_result = run_tests(tag, containerfile, host=self._host, timeout=300)

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
            if self._host:
                delimiter = f"CONTAINERFILE_EOF_{uuid.uuid4().hex[:8]}"
                safe_containerfile = containerfile.replace(delimiter, "")
                cache_flag = " --no-cache" if self._no_cache else ""
                build_cmd = (
                    f"cd $(mktemp -d) && "
                    f"cat > Containerfile << '{delimiter}'\n{safe_containerfile}\n{delimiter}\n"
                    f"podman build{cache_flag} -t {tag} -f Containerfile ."
                )
                proc = self._run_shell(
                    build_cmd,
                    capture_output=True, text=True, timeout=self._timeout,
                )
            else:
                import tempfile as _tmpfile
                build_dir = _tmpfile.mkdtemp(prefix="buildroot-l2-")
                cf_path = Path(build_dir) / "Containerfile"
                cf_path.write_text(containerfile)
                build_cmd_list = ["podman", "build"]
                if self._no_cache:
                    build_cmd_list.append("--no-cache")
                build_cmd_list.extend(["-t", tag, "-f", str(cf_path), build_dir])
                proc = self._run(
                    build_cmd_list,
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
                "find target/ build/libs/ */target/ */build/libs/ "
                "-name '*.jar' "
                "-not -name '*-sources.jar' "
                "-not -name '*-javadoc.jar' "
                "-not -name 'original-*.jar' "
                "2>/dev/null | head -1 | grep -q . "
                "&& echo BUILD_SUCCESS || echo BUILD_FAILED"
            )
            proc = self._run(
                ["podman", "run", "--rm", tag, "sh", "-c", check_cmd],
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
        try:
            cached = get_jar_path(group_id, artifact_id, version)
            jar_path = dest / f"{artifact_id}-{version}-original.jar"
            shutil.copy2(cached, jar_path)
            return jar_path
        except (requests.RequestException, ValueError, OSError) as e:
            logger.warning("Could not obtain original JAR: %s", e)
            return None

    def _extract_rebuilt_jar(
        self, tag: str, artifact_id: str, version: str, dest: Path
    ) -> Path | None:
        try:
            find_cmd = (
                "find /build target -name '*.jar' -not -name '*-sources.jar' "
                "-not -name '*-javadoc.jar' -not -name 'original-*.jar' 2>/dev/null "
                "| head -5"
            )
            proc = self._run(
                ["podman", "run", "--rm", tag, "sh", "-c", find_cmd],
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
            copy_proc = self._run(
                ["podman", "run", "--rm", tag, "cat", target_jar],
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

    def _l1_5_trust_check(self, containerfile: str, result: EvalResult) -> bool:
        """Verify all FROM lines use trusted base images."""
        parser = DockerfileParser()
        parser.content = containerfile
        structure = parser.structure

        args = self._parse_dockerfile_args(structure)
        violations = []

        for instruction in structure:
            if instruction["instruction"] == "FROM":
                value = instruction["value"].split()[0]
                image = self._substitute_args(value, args)
                has_unresolved = "${" in image or "$" in image
                has_empty_sub = any(
                    v == ""
                    and re.search(
                        r"\$\{" + re.escape(k) + r"\}|\$" + re.escape(k) + r"\b",
                        value,
                    )
                    for k, v in args.items()
                )
                if has_unresolved or has_empty_sub:
                    violations.append(
                        f"FROM {value} — unresolved build argument"
                    )
                elif image == "scratch":
                    continue
                elif not self._is_trusted_image(image):
                    violations.append(
                        f"FROM {image} — not in trusted allowlist"
                    )

        if violations:
            result.trust_violations = violations
            result.trust_check = False
            result.error_summary = (
                f"Trust check failed: {len(violations)} untrusted source(s) detected"
            )
            return False

        result.trust_check = True
        return True

    def _is_trusted_image(self, image: str) -> bool:
        """Check if an image reference matches the trusted allowlist."""
        normalized = image
        if normalized.startswith("index.docker.io/"):
            normalized = "docker.io/" + normalized[len("index.docker.io/"):]

        if not normalized.startswith("docker.io/") and not normalized.startswith("registry."):
            if "/" not in normalized or "." not in normalized.split("/")[0]:
                normalized = "docker.io/library/" + normalized

        if normalized.startswith("docker.io/") and not normalized.startswith("docker.io/library/"):
            rest = normalized[len("docker.io/"):]
            if "/" not in rest:
                normalized = "docker.io/library/" + rest

        return any(pat.search(normalized) for pat in TRUSTED_IMAGE_PATTERNS)

    def _parse_dockerfile_args(self, structure: list) -> dict:
        """Extract ARG instructions with defaults."""
        args = {}
        for instruction in structure:
            if instruction["instruction"] == "ARG":
                value = instruction["value"].strip()
                if "=" in value:
                    key, default = value.split("=", 1)
                    args[key.strip()] = default.strip()
                else:
                    args[value] = ""
        return args

    def _substitute_args(self, text: str, args: dict) -> str:
        """Replace ${VAR} and $VAR patterns with values from args dict."""
        import re as _re
        def replacer(m):
            var = m.group(1) or m.group(2)
            return args.get(var, m.group(0))
        return _re.sub(r"\$\{(\w+)\}|\$(\w+)", replacer, text)

    def _cleanup_image(self, tag: str) -> None:
        try:
            self._run(
                ["podman", "rmi", "-f", tag],
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
