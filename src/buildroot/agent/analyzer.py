"""Analyzer — error pattern constants, build progress tracking, and dead-end registry."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from buildroot.agent.models import DeadEndEntry

logger = logging.getLogger(__name__)

GHA_EXPRESSION_RE = re.compile(r"\$\{\{[^}]*\}\}")


def sanitize_gha_expressions(containerfile: str) -> str:
    """Strip GitHub Actions expressions that leak from CI workflows into Containerfiles."""
    lines = []
    for line in containerfile.splitlines():
        if GHA_EXPRESSION_RE.search(line):
            stripped = line.strip()
            if stripped.startswith("ARG ") or stripped.startswith("ENV "):
                key_match = re.match(r"(ARG|ENV)\s+(\w+)=", stripped)
                if key_match:
                    lines.append(f"{key_match.group(1)} {key_match.group(2)}=")
                    continue
            cleaned = GHA_EXPRESSION_RE.sub("", line)
            if cleaned.strip():
                lines.append(cleaned)
        else:
            lines.append(line)
    return "\n".join(lines)


ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("containerfile/parse_error", re.compile(
        r"stage 1 requires a FROM instruction|"
        r"Dockerfile parse error|"
        r"failed to parse Dockerfile|"
        r"Error: FROM requires", re.IGNORECASE
    )),
    ("build_tool/wrong_build_system", re.compile(
        r"gradle:?\s*(not found|command not found)|"
        r"no POM in this directory|"
        r"Could not find or load main class org\.gradle|"
        r"gradlew:?\s*(not found|No such file)", re.IGNORECASE
    )),
    ("build_tool/multi_module", re.compile(
        r"Could not find artifact .* in reactor|"
        r"Non-resolvable parent POM", re.IGNORECASE
    )),
    ("dependency_resolution/missing_artifact", re.compile(
        r"Could not (resolve|find) (artifact|dependencies)", re.IGNORECASE
    )),
    ("dependency_resolution/version_conflict", re.compile(
        r"version conflict|Dependency convergence error", re.IGNORECASE
    )),
    ("compilation/jdk_mismatch", re.compile(
        r"(source|target) (option|release) \d+ is not supported|"
        r"invalid (source|target) release|"
        r"class file has wrong version", re.IGNORECASE
    )),
    ("compilation/syntax_error", re.compile(
        r"\[ERROR\].*\.java:\[\d+,\d+\]|"
        r"error: cannot find symbol|"
        r"error: package .* does not exist", re.IGNORECASE
    )),
    ("plugin/configuration_error", re.compile(
        r"Failed to execute goal .* on project|"
        r"Plugin .* or one of its dependencies could not be resolved", re.IGNORECASE
    )),
    ("plugin/gpg_error", re.compile(
        r"gpg: signing failed|Cannot run program \"gpg\"", re.IGNORECASE
    )),
    ("environment/gha_secrets", re.compile(
        r"\$\{\{\s*secrets\.", re.IGNORECASE
    )),
    ("environment/gha_expressions", re.compile(
        r"\$\{\{.*\}\}", re.IGNORECASE
    )),
    ("environment/image_resolution", re.compile(
        r"short-name .* did not resolve|"
        r"Failed to resolve image|"
        r"manifest unknown", re.IGNORECASE
    )),
    ("source/wrong_tag", re.compile(
        r"fatal: Remote branch .* not found|"
        r"fatal: couldn't find remote ref|"
        r"error: pathspec .* did not match", re.IGNORECASE
    )),
    ("source/clone_failed", re.compile(
        r"fatal: repository .* not found|"
        r"fatal: could not read from remote", re.IGNORECASE
    )),
    ("build_tool/maven_wrapper", re.compile(
        r"mvnw: No such file|"
        r"./mvnw: Permission denied|"
        r"Error: Could not find or load main class", re.IGNORECASE
    )),
    ("resource/oom", re.compile(
        r"java\.lang\.OutOfMemoryError|"
        r"GC overhead limit exceeded|"
        r"insufficient memory", re.IGNORECASE
    )),
    ("resource/disk_space", re.compile(
        r"No space left on device|"
        r"ENOSPC", re.IGNORECASE
    )),
    ("environment/credentials", re.compile(
        r"401 Unauthorized|"
        r"403 Forbidden|"
        r"authentication required", re.IGNORECASE
    )),
    ("environment/obsolete_jvm_flag", re.compile(
        r"Unrecognized VM option|"
        r"MaxPermSize|"
        r"PermSize|"
        r"Unrecognized option:.*-XX:", re.IGNORECASE
    )),
    ("l3/jar_not_found", re.compile(
        r"BUILD_FAILED.*no.*JAR|"
        r"BUILD_FAILED.*\.jar|"
        r"No \.jar files? found|"
        r"ls:.*target/\*\.jar.*No such file", re.IGNORECASE
    )),
    ("l4/structural_divergence", re.compile(
        r"structural_match=False", re.IGNORECASE
    )),
    ("l4/metadata_mismatch", re.compile(
        r"metadata_match=False", re.IGNORECASE
    )),
    ("l4/bytecode_divergence", re.compile(
        r"bytecode_match=False", re.IGNORECASE
    )),
]

FUNDAMENTAL_BLOCKERS = frozenset({
    "environment/credentials",
    "source/clone_failed",
})

# ---------------------------------------------------------------------------
# Build progress estimation — sub-level tracking within Maven lifecycle
# ---------------------------------------------------------------------------

BUILD_PHASES = [
    "initialization",
    "dependency_resolution",
    "compilation",
    "testing",
    "packaging",
    "installation",
]

_PHASE_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("initialization", re.compile(
        r"Building .+ \d|Scanning for projects|Reactor Build Order",
        re.IGNORECASE,
    )),
    ("dependency_resolution", re.compile(
        r"Downloading from |Downloaded from |Resolving dependencies",
        re.IGNORECASE,
    )),
    ("compilation", re.compile(
        r"maven-compiler-plugin.*:compile|"
        r"Compiling \d+ source file|"
        r"kotlinc|"
        r"scala-maven-plugin.*:compile",
        re.IGNORECASE,
    )),
    ("testing", re.compile(
        r"maven-surefire-plugin|maven-failsafe-plugin|Tests run:|"
        r"Running .*Test",
        re.IGNORECASE,
    )),
    ("packaging", re.compile(
        r"maven-jar-plugin|maven-war-plugin|maven-shade-plugin|"
        r"Building jar:|Building war:",
        re.IGNORECASE,
    )),
    ("installation", re.compile(
        r"maven-install-plugin|Installing .* to .*\.m2",
        re.IGNORECASE,
    )),
]


@dataclass
class BuildProgress:
    """Tracks how far a build got in the Maven lifecycle."""

    phase_reached: str = "none"
    phase_index: int = -1
    phases_completed: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        if self.phase_index < 0:
            return "Build did not start or produced no recognizable output."
        completed = ", ".join(self.phases_completed)
        return (
            f"Build reached '{self.phase_reached}' phase "
            f"(phases seen: {completed})"
        )


@dataclass
class RootCauseDetail:
    """Structured details about a specific root cause entity."""

    cause_type: str = "unknown"
    specific_entity: str = ""
    raw_match: str = ""

    def __str__(self) -> str:
        return f"[{self.cause_type}] {self.specific_entity}"


_ROOT_CAUSE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("missing_artifact", re.compile(
        r"Could not (?:resolve|find) artifact ([^\s]+)", re.IGNORECASE,
    )),
    ("missing_class", re.compile(
        r"error: cannot find symbol.*?symbol:\s*(?:class|variable)\s+(\S+)",
        re.DOTALL,
    )),
    ("missing_package", re.compile(
        r"error: package (\S+) does not exist", re.IGNORECASE,
    )),
    ("failing_plugin", re.compile(
        r"Failed to execute goal ([^\s]+)", re.IGNORECASE,
    )),
    ("unsupported_source_level", re.compile(
        r"(?:source|target) (?:option|release) (\d+) is not supported",
        re.IGNORECASE,
    )),
    ("missing_repository", re.compile(
        r"Could not transfer artifact .* from/to (\S+)",
        re.IGNORECASE,
    )),
]


def estimate_build_progress(build_log: str) -> BuildProgress:
    """Estimate how far the build got by scanning for Maven lifecycle phase markers."""
    if not build_log:
        return BuildProgress()

    progress = BuildProgress()
    for i, (phase_name, pattern) in enumerate(_PHASE_MARKERS):
        if pattern.search(build_log):
            if i > progress.phase_index:
                progress.phase_reached = phase_name
                progress.phase_index = i
            progress.phases_completed.append(phase_name)

    return progress


def extract_root_cause_details(
    error_summary: str, build_log: str,
) -> list[RootCauseDetail]:
    """Extract specific root-cause entities from the build output."""
    combined = f"{error_summary}\n{build_log}"
    details: list[RootCauseDetail] = []
    seen: set[str] = set()

    for cause_type, pattern in _ROOT_CAUSE_PATTERNS:
        for match in pattern.finditer(combined):
            entity = match.group(1) if match.lastindex else match.group(0)
            key = f"{cause_type}:{entity}"
            if key not in seen:
                seen.add(key)
                details.append(RootCauseDetail(
                    cause_type=cause_type,
                    specific_entity=entity,
                    raw_match=match.group(0)[:200],
                ))
    return details


def compute_progress_delta(
    current: BuildProgress, previous: BuildProgress | None,
) -> str:
    """Describe the progress change between two iterations."""
    if previous is None:
        return f"First iteration — reached phase: {current.phase_reached}"
    if current.phase_index > previous.phase_index:
        return (
            f"FORWARD PROGRESS: advanced from '{previous.phase_reached}' "
            f"to '{current.phase_reached}'"
        )
    if current.phase_index == previous.phase_index:
        return f"STALLED at '{current.phase_reached}' — same phase as last iteration"
    return (
        f"REGRESSION: went from '{previous.phase_reached}' "
        f"back to '{current.phase_reached}'"
    )


def suggest_relaxation_flags(
    error_class: str, build_progress: BuildProgress,
) -> list[str]:
    """Suggest Maven flags to progressively skip problematic build phases.

    Returns a list of ``-D...`` flags ordered from least to most aggressive.
    These are generic Maven flags, not package-specific.
    """
    flags: list[str] = []

    # If build reached testing phase, tests may be the blocker
    if build_progress.phase_index >= BUILD_PHASES.index("testing"):
        flags.append("-DskipTests")

    # Plugin-related errors: skip common optional enforcement/checking plugins
    if "plugin" in error_class:
        flags.extend([
            "-Dcheckstyle.skip=true",
            "-Denforcer.skip=true",
            "-Danimal.sniffer.skip=true",
            "-Dmaven.javadoc.skip=true",
            "-Dpmd.skip=true",
            "-Dspotbugs.skip=true",
            "-Drat.skip=true",
            "-Djacoco.skip=true",
        ])

    if "gpg" in error_class:
        flags.append("-Dgpg.skip=true")

    if "obsolete_jvm_flag" in error_class:
        flags.append("-Darguments=")  # clear MAVEN_OPTS-like injections

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


@dataclass
class AnalysisResult:
    error_class: str
    error_summary: str
    fix_suggestion: str
    is_fundamental_blocker: bool = False
    build_log_excerpt: str = ""
    build_progress: BuildProgress = field(default_factory=BuildProgress)
    root_cause_details: list[RootCauseDetail] = field(default_factory=list)
    relaxation_flags: list[str] = field(default_factory=list)


_ERROR_LINE_RE = re.compile(
    r"\[ERROR\]|FAILURE|BUILD FAILED|"
    r"error:|Error:|ERROR:|"
    r"Could not|Cannot|Failed to|"
    r"fatal:|FATAL:|"
    r"Exception|Caused by:",
)


def extract_build_log_excerpt(build_log: str, max_lines: int = 50) -> str:
    """Extract the most relevant error-context lines from a build log.

    Scans for error indicators and returns surrounding context (±2 lines).
    Falls back to the tail of the log when no explicit error lines are found.
    """
    if not build_log:
        return ""

    lines = build_log.splitlines()
    relevant: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        if _ERROR_LINE_RE.search(line):
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                relevant.append((j, lines[j]))

    if not relevant:
        # No explicit error markers — return the tail (often contains the error)
        return "\n".join(lines[-max_lines:])

    # Deduplicate by line number, preserve order
    seen: set[int] = set()
    unique: list[str] = []
    for idx, line in sorted(relevant):
        if idx not in seen:
            seen.add(idx)
            unique.append(line)

    return "\n".join(unique[:max_lines])


def detect_error_loop(error_history: list[str]) -> tuple[bool, str]:
    """Detect repeating patterns in the error-class sequence.

    Returns ``(is_loop, description)`` — True when the same error repeats 3+
    times or two errors alternate (A-B-A-B oscillation).
    """
    if len(error_history) < 3:
        return False, ""

    # Simple repetition — same error 3+ times in a row
    recent3 = error_history[-3:]
    if len(set(recent3)) == 1:
        return True, (
            f"Same error '{recent3[0]}' repeated {len(recent3)} consecutive times — "
            "targeted fixes are not working"
        )

    # Oscillation — A-B-A-B pattern in the last 4 entries
    if len(error_history) >= 4:
        last4 = error_history[-4:]
        if last4[0] == last4[2] and last4[1] == last4[3] and last4[0] != last4[1]:
            return True, (
                f"Oscillating between '{last4[0]}' and '{last4[1]}' — "
                "fixing one causes the other"
            )

    return False, ""


def extract_build_signature(containerfile: str) -> str:
    """Extract a rich build signature from a Containerfile for dead-end deduplication.

    Includes FROM line, build command, ENV variables, and build flags.
    """
    lines = containerfile.splitlines()
    from_line = ""
    build_cmd = ""
    env_vars = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FROM ") and not from_line:
            from_line = stripped[:80]
        if stripped.startswith("RUN ") and (
            "mvn " in stripped or "maven" in stripped.lower()
            or "gradle" in stripped.lower() or "gradlew" in stripped
            or "ant " in stripped
        ):
            build_cmd = stripped[:120]
        if stripped.startswith("ENV "):
            env_vars.append(stripped[:60])

    parts = [from_line or "unknown"]
    if build_cmd:
        parts.append(build_cmd)
    if env_vars:
        parts.append(" | ".join(env_vars[:5]))
    return " | ".join(parts)


def update_dead_ends(
    dead_ends: list[DeadEndEntry],
    error_class: str,
    approach: str,
    log_summary: str,
) -> None:
    """Record a failure in the dead-end registry. Creates entry if needed."""
    key = f"{error_class}::{approach}"
    for entry in dead_ends:
        if f"{entry.error_class}::{entry.approach}" == key:
            entry.record_failure(log_summary)
            return
    entry = DeadEndEntry(error_class=error_class, approach=approach)
    entry.record_failure(log_summary)
    dead_ends.append(entry)


def all_exhausted(dead_ends: list[DeadEndEntry]) -> bool:
    """Check if all registered approaches are exhausted."""
    if not dead_ends:
        return False
    return all(de.is_exhausted for de in dead_ends)


