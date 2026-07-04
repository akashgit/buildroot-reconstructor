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
from buildroot.trust.registry import TrustedSourceRegistry
from buildroot.utils.jar_comparator import compare_jars
from buildroot.utils.maven_central import get_jar_path

logger = logging.getLogger(__name__)


class Evaluator:
    """Runs 4-level evaluation: parse, build, command, JAR match."""

    def __init__(self, host: str | None = None, timeout: int = 900, no_cache: bool = False) -> None:
        self._host = host
        self._timeout = timeout
        self._no_cache = no_cache
        self._trust_registry = TrustedSourceRegistry()

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
        jdk_version: str = "",
    ) -> EvalResult:
        containerfile = sanitize_gha_expressions(containerfile)
        result = EvalResult()

        if not self._l1_parse(containerfile, result):
            result.compute_reward()
            return result

        self._l1_5_trust(containerfile, result)
        if trusted and result.trust_violations:
            result.error_summary = "; ".join(result.trust_violations)
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

        self._l4_match(tag, coordinate, result, jdk_version=jdk_version)
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

    def _l1_5_trust(self, containerfile: str, result: EvalResult) -> bool:
        """L1.5 trust gate: verify FROM images and download URLs are trusted."""
        violations: list[str] = []

        parser = DockerfileParser()
        parser.content = containerfile
        for instruction in parser.structure:
            if instruction["instruction"] == "FROM":
                image_ref = instruction["value"].split()[0]
                if image_ref.upper() == "SCRATCH":
                    continue
                trusted, _ = self._trust_registry.is_trusted_image(image_ref)
                if not trusted:
                    violations.append(
                        f"Untrusted base image: {image_ref}"
                    )

        for line_num, url in _extract_download_urls(containerfile):
            if not self._trust_registry.is_trusted_download_url(url):
                violations.append(
                    f"Untrusted download URL at line {line_num}: {url}"
                )

        if violations:
            result.trust_violations = violations
            logger.warning("L1.5 trust violations: %s", violations)

        return True

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

    def _l4_match(self, tag: str, coordinate: str, result: EvalResult, *, jdk_version: str = "") -> None:
        group_id, artifact_id, version = parse_gav(coordinate)
        try:
            with tempfile.TemporaryDirectory(prefix="buildroot-l4-") as tmpdir:
                tmp = Path(tmpdir)
                original_jar = self._download_original_jar(
                    group_id, artifact_id, version, tmp
                )
                if not original_jar:
                    signals = self.l4_fallback_signals(tag, coordinate, jdk_version)
                    test_pass = None
                    if result.test_result and result.test_result.available:
                        test_pass = result.test_result.passed

                    from buildroot.agent.scorer import compute_fallback_score
                    fallback = compute_fallback_score(
                        signals.get("bytecode_version_match"),
                        signals.get("manifest_sanity"),
                        test_pass,
                        signals.get("structural_match"),
                    )
                    result.l4_score = fallback
                    result.bytecode_version_match = signals.get("bytecode_version_match")
                    result.manifest_sanity = signals.get("manifest_sanity")
                    result.unit_tests_pass = test_pass
                    result.structural_match = signals.get("structural_match")
                    result.l4_signal_source = "fallback_signals"
                    result.error_summary = (
                        f"L4 (approximate): fallback score = {fallback:.2f} (JAR unavailable)"
                    )
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
                result.l4_signal_source = "full_comparison"
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

    def _create_container(self, tag: str) -> str | None:
        """Create a stopped container from an image, returning the container ID."""
        try:
            proc = self._run(
                ["podman", "create", tag, "true"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
            return None
        except Exception as e:
            logger.warning("Could not create container from %s: %s", tag, e)
            return None

    def _remove_container(self, container_id: str) -> None:
        """Remove a stopped container."""
        try:
            self._run(
                ["podman", "rm", container_id],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass

    def _extract_rebuilt_jar(
        self, tag: str, artifact_id: str, version: str, dest: Path,
        *, container_id: str | None = None,
    ) -> Path | None:
        try:
            own_container = False
            if container_id is None:
                container_id = self._create_container(tag)
                own_container = True
                if not container_id:
                    return None

            try:
                return self._extract_jar_from_container(
                    container_id, artifact_id, version, dest,
                )
            finally:
                if own_container:
                    self._remove_container(container_id)
        except Exception as e:
            logger.warning("Could not extract rebuilt JAR: %s", e)
            return None

    def _extract_jar_from_container(
        self, container_id: str, artifact_id: str, version: str, dest: Path,
    ) -> Path | None:
        """Extract JAR from a stopped container using podman cp."""
        jar_dir = dest / "jars"
        jar_dir.mkdir(parents=True, exist_ok=True)

        for src_path in ["/build/target", "/build/build/libs", "target", "build/libs"]:
            cp_proc = self._run(
                ["podman", "cp", f"{container_id}:{src_path}/.", str(jar_dir)],
                capture_output=True, text=True, timeout=60,
            )
            if cp_proc.returncode == 0:
                break

        jar_files = [
            p for p in jar_dir.rglob("*.jar")
            if not p.name.endswith("-sources.jar")
            and not p.name.endswith("-javadoc.jar")
            and not p.name.startswith("original-")
        ]
        if not jar_files:
            return None

        target_jar = None
        for jp in jar_files:
            if artifact_id in jp.name and version in jp.name:
                target_jar = jp
                break
        if not target_jar:
            target_jar = jar_files[0]

        local_jar = dest / f"{artifact_id}-{version}-rebuilt.jar"
        shutil.copy2(target_jar, local_jar)
        return local_jar

    def l4_fallback_signals(
        self, tag: str, coordinate: str, jdk_version: str = "",
    ) -> dict:
        """Compute fallback L4 signals when no original JAR is available.

        Returns dict with bytecode_version_match, manifest_sanity, structural_match keys.
        Uses podman create + podman cp (not podman run) to avoid container startup overhead.
        """
        from buildroot.agent.scorer import (
            check_bytecode_version_match,
            check_manifest_sanity,
            check_structural_match,
        )

        group_id, artifact_id, version = parse_gav(coordinate)
        signals: dict = {}

        container_id = self._create_container(tag)
        if not container_id:
            logger.warning("Could not create container for fallback signals")
            return signals

        try:
            with tempfile.TemporaryDirectory(prefix="buildroot-fb-") as tmpdir:
                tmp = Path(tmpdir)
                rebuilt_jar = self._extract_rebuilt_jar(
                    tag, artifact_id, version, tmp, container_id=container_id,
                )
                if rebuilt_jar:
                    if jdk_version:
                        signals["bytecode_version_match"] = check_bytecode_version_match(
                            rebuilt_jar, jdk_version,
                        )
                    signals["manifest_sanity"] = check_manifest_sanity(
                        rebuilt_jar, group_id, artifact_id,
                    )
                    source_root = self._extract_source_root(
                        tag, tmp / "source", container_id=container_id,
                        artifact_id=artifact_id,
                    )
                    if source_root:
                        signals["structural_match"] = check_structural_match(
                            rebuilt_jar, source_root,
                        )
        except Exception as e:
            logger.warning("Fallback signal extraction failed: %s", e)
        finally:
            self._remove_container(container_id)

        return signals

    def _extract_source_root(
        self, tag: str, dest: Path, *, container_id: str | None = None,
        artifact_id: str = "",
    ) -> Path | None:
        """Extract the source tree from a container image using podman cp."""
        try:
            own_container = False
            if container_id is None:
                container_id = self._create_container(tag)
                own_container = True
                if not container_id:
                    return None

            try:
                return self._extract_source_from_container(
                    container_id, dest, artifact_id=artifact_id,
                )
            finally:
                if own_container:
                    self._remove_container(container_id)
        except Exception as e:
            logger.warning("Could not extract source root: %s", e)
            return None

    def _extract_source_from_container(
        self, container_id: str, dest: Path, *, artifact_id: str = "",
    ) -> Path | None:
        """Extract source tree from a stopped container using podman cp."""
        dest.mkdir(parents=True, exist_ok=True)

        cp_proc = self._run(
            ["podman", "cp", f"{container_id}:/build/src/.", str(dest)],
            capture_output=True, text=True, timeout=60,
        )
        if cp_proc.returncode == 0:
            java_files = list(dest.rglob("*.java"))
            if java_files:
                return dest

        if artifact_id:
            submod_names = [artifact_id]
            parts = artifact_id.split("-")
            if len(parts) > 1:
                submod_names.append(parts[-1])
            for submod in submod_names:
                sub_dest = dest / submod
                sub_dest.mkdir(parents=True, exist_ok=True)
                cp_proc = self._run(
                    ["podman", "cp", f"{container_id}:/build/{submod}/src/.", str(sub_dest)],
                    capture_output=True, text=True, timeout=60,
                )
                if cp_proc.returncode == 0:
                    java_files = list(sub_dest.rglob("*.java"))
                    if java_files:
                        return sub_dest

        return None

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


def _extract_download_urls(containerfile_content: str) -> list[tuple[int, str]]:
    """Extract URLs from RUN curl/wget and ADD directives.

    Returns list of (line_number, url) tuples.
    """
    results: list[tuple[int, str]] = []
    url_re = re.compile(r'https?://\S+')

    for line_num, line in enumerate(containerfile_content.splitlines(), 1):
        stripped = line.strip()

        if stripped.upper().startswith("ADD "):
            parts = stripped.split()
            if len(parts) >= 2:
                src = parts[1]
                if src.startswith(("http://", "https://")):
                    results.append((line_num, src))
            continue

        if stripped.upper().startswith("RUN "):
            cmd_part = stripped[4:]
        elif stripped.startswith(("&&", "|")):
            cmd_part = stripped.lstrip("&|").strip()
        else:
            continue

        tokens = cmd_part.split()
        for i, token in enumerate(tokens):
            if token in ("curl", "wget"):
                for url_match in url_re.finditer(" ".join(tokens[i:])):
                    results.append((line_num, url_match.group()))

    return results


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
