"""Built-in test detection and execution for reconstructed packages."""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import time

from buildroot.agent.models import TestResult

logger = logging.getLogger(__name__)

_MAVEN_SUMMARY_RE = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)"
)

_GRADLE_RESULT_RE = re.compile(
    r"(\d+)\s+tests?\s+completed,\s*(\d+)\s+failed"
)

_GRADLE_SKIPPED_RE = re.compile(
    r"(\d+)\s+tests?\s+skipped"
)

_GRADLE_SUMMARY_RE = re.compile(
    r"(\d+)\s+tests?\s+completed"
)

_FAILURE_BLOCK_RE = re.compile(
    r"(?:FAILED|FAILURE|ERROR)[^\n]*\n((?:[ \t]+[^\n]+\n?){1,10})",
    re.MULTILINE,
)


def detect_test_framework(containerfile: str) -> str | None:
    """Detect the build/test framework from a Containerfile's content.

    Returns 'maven', 'gradle', 'ant', or None.
    Gradle is checked before Maven so mixed projects default to Gradle.
    """
    lower = containerfile.lower()
    if "gradlew" in lower or "build.gradle" in lower or "gradle " in lower:
        return "gradle"
    if "mvn " in lower or "pom.xml" in lower:
        return "maven"
    if "ant " in lower or "build.xml" in lower:
        return "ant"
    return None


def build_test_command(framework: str, module_path: str | None = None) -> str:
    """Return the framework-appropriate test command string."""
    if framework == "maven":
        if module_path:
            return f"mvn test -B -pl {shlex.quote(module_path)}"
        return "mvn test -B"
    if framework == "gradle":
        if module_path:
            return f"./gradlew :{shlex.quote(module_path)}:test"
        return "./gradlew test"
    if framework == "ant":
        return "ant test"
    return ""


def parse_maven_test_output(stdout: str) -> dict:
    """Extract test counts from Maven's output.

    Aggregates across all `Tests run:` lines (multi-module builds produce one per module).
    Returns dict with run, tests_passed, failed, skipped, failures.
    """
    total_run = 0
    total_failures = 0
    total_errors = 0
    total_skipped = 0

    for m in _MAVEN_SUMMARY_RE.finditer(stdout):
        total_run += int(m.group(1))
        total_failures += int(m.group(2))
        total_errors += int(m.group(3))
        total_skipped += int(m.group(4))

    failed = total_failures + total_errors
    passed = total_run - failed - total_skipped

    failure_details: list[str] = []
    for m in _FAILURE_BLOCK_RE.finditer(stdout):
        detail = m.group(0).strip()
        if detail and len(failure_details) < 5:
            failure_details.append(detail[:500])

    return {
        "run": total_run,
        "tests_passed": max(passed, 0),
        "failed": failed,
        "skipped": total_skipped,
        "failures": failure_details,
    }


def parse_gradle_test_output(stdout: str) -> dict:
    """Extract test counts from Gradle's output.

    Returns dict with run, tests_passed, failed, skipped, failures.
    """
    total_run = 0
    total_failed = 0
    total_skipped = 0

    for m in _GRADLE_RESULT_RE.finditer(stdout):
        total_run += int(m.group(1))
        total_failed += int(m.group(2))

    if total_run == 0:
        for m in _GRADLE_SUMMARY_RE.finditer(stdout):
            total_run += int(m.group(1))

    for m in _GRADLE_SKIPPED_RE.finditer(stdout):
        total_skipped += int(m.group(1))

    passed = total_run - total_failed - total_skipped

    failure_details: list[str] = []
    for m in _FAILURE_BLOCK_RE.finditer(stdout):
        detail = m.group(0).strip()
        if detail and len(failure_details) < 5:
            failure_details.append(detail[:500])

    return {
        "run": total_run,
        "tests_passed": max(passed, 0),
        "failed": total_failed,
        "skipped": total_skipped,
        "failures": failure_details,
    }


def run_tests(
    tag: str,
    containerfile: str,
    host: str | None = None,
    timeout: int = 300,
    podman_root: str | None = None,
    podman_runroot: str | None = None,
    podman_tmpdir: str | None = None,
) -> TestResult | None:
    """Run the project's test suite inside the build container.

    Returns TestResult with parsed results, or None if no test framework detected.
    """
    framework = detect_test_framework(containerfile)
    if not framework:
        return None

    command = build_test_command(framework)

    if framework == "maven":
        cd_prefix = (
            "POM=$(find . -maxdepth 5 -name pom.xml -type f 2>/dev/null | sort | head -1); "
            "if [ -n \"$POM\" ]; then cd \"$(dirname \"$POM\")\" 2>/dev/null || true; fi; "
        )
    elif framework == "gradle":
        cd_prefix = (
            "GW=$(find . -maxdepth 5 -name gradlew -type f 2>/dev/null | sort | head -1); "
            "if [ -n \"$GW\" ]; then cd \"$(dirname \"$GW\")\" 2>/dev/null || true; fi; "
        )
    else:
        cd_prefix = ""
    command = cd_prefix + command

    result = TestResult(
        available=True,
        framework=framework,
        command=command,
    )

    podman_bin = "podman"
    if podman_root:
        podman_bin += f" --root {shlex.quote(podman_root)}"
    if podman_runroot:
        podman_bin += f" --runroot {shlex.quote(podman_runroot)}"
    if podman_tmpdir:
        podman_bin += f" --tmpdir {shlex.quote(podman_tmpdir)}"
    podman_cmd = f"{podman_bin} run --rm {shlex.quote(tag)} sh -c {shlex.quote(command)}"
    if host:
        cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            host, podman_cmd,
        ]
    else:
        podman_base = ["podman"]
        if podman_root:
            podman_base += ["--root", podman_root]
        if podman_runroot:
            podman_base += ["--runroot", podman_runroot]
        if podman_tmpdir:
            podman_base += ["--tmpdir", podman_tmpdir]
        cmd = podman_base + ["run", "--rm", tag, "sh", "-c", command]

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        elapsed = time.monotonic() - start
        result.duration_seconds = round(elapsed, 1)
        output = proc.stdout + proc.stderr

        if framework == "maven":
            counts = parse_maven_test_output(output)
        elif framework == "gradle":
            counts = parse_gradle_test_output(output)
        else:
            result.status = "passed" if proc.returncode == 0 else "failed"
            result.passed = proc.returncode == 0
            return result

        result.run = counts["run"]
        result.tests_passed = counts["tests_passed"]
        result.failed = counts["failed"]
        result.skipped = counts["skipped"]
        result.failures = counts["failures"]

        if proc.returncode == 0 and counts["failed"] == 0:
            result.passed = True
            result.status = "passed"
        else:
            result.passed = False
            result.status = "failed"

    except subprocess.TimeoutExpired:
        result.duration_seconds = float(timeout)
        result.status = "timeout"
        result.passed = False
    except OSError as e:
        logger.warning("Test runner SSH error: %s", e)
        result.status = "error"
        result.passed = False

    return result
