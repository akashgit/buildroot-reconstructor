"""Analyzer agent — error classification, dead-end registry, and G_t progress signal."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from buildroot.agent.claude_runner import spawn_claude_agent
from buildroot.agent.models import DeadEndEntry, EvalResult

logger = logging.getLogger(__name__)


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


def build_remediation_context(
    analysis_result: AnalysisResult,
    build_log: str,
    error_history: list[str] | None = None,
    previous_progress: BuildProgress | None = None,
) -> str:
    """Produce a rich remediation-context block for the builder agent.

    Bridges the analyzer→builder gap by packaging fix suggestions,
    key build-log lines, error-trajectory warnings, build progress,
    and root-cause details into a single structured prompt section.
    """
    sections: list[str] = []

    # 1. Build progress — where did the build get to?
    progress = analysis_result.build_progress
    sections.append(f"## Build Progress\n{progress.description}")
    if previous_progress is not None:
        delta = compute_progress_delta(progress, previous_progress)
        sections.append(f"## Progress Delta\n{delta}")

    # 2. Root cause details — specific entities that failed
    if analysis_result.root_cause_details:
        rc_lines = [str(rc) for rc in analysis_result.root_cause_details]
        sections.append(
            "## Root Cause Details\n" + "\n".join(f"- {line}" for line in rc_lines)
        )

    # 3. Actionable fix direction from the analyzer
    sections.append(f"## Recommended Fix Direction\n{analysis_result.fix_suggestion}")

    # 4. Relaxation flags if applicable
    if analysis_result.relaxation_flags:
        flag_str = " ".join(analysis_result.relaxation_flags)
        sections.append(
            f"## Suggested Build Flags\n"
            f"Consider adding to the build command: {flag_str}"
        )

    # 5. Key error lines from the actual build log
    excerpt = analysis_result.build_log_excerpt or extract_build_log_excerpt(build_log)
    if excerpt:
        sections.append(f"## Key Build Log Lines\n{excerpt}")

    # 6. Error trajectory / loop detection
    if error_history:
        is_loop, loop_desc = detect_error_loop(error_history)
        if is_loop:
            sections.append(
                f"## ⚠ ERROR LOOP DETECTED\n{loop_desc}\n"
                "You MUST take a fundamentally different approach — "
                "do not make incremental changes to the same strategy."
            )
        elif len(error_history) >= 2:
            recent = error_history[-5:]
            trajectory = " → ".join(recent)
            sections.append(f"## Error Trajectory\n{trajectory}")

    return "\n\n".join(sections)


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


def classify_error(error_summary: str, build_log: str = "") -> str:
    """Classify a build error using regex patterns. Returns the error class string."""
    combined = f"{error_summary}\n{build_log}"
    for error_class, pattern in ERROR_PATTERNS:
        if pattern.search(combined):
            return error_class
    return "unknown"


def analyze(eval_result: EvalResult, dead_ends: list[DeadEndEntry]) -> AnalysisResult:
    """Full analysis: classify error, check dead-ends, suggest fix."""
    error_class = classify_error(
        eval_result.error_summary, eval_result.build_log
    )

    fix_suggestion = _suggest_fix(error_class, eval_result.error_summary)

    is_blocker = error_class in FUNDAMENTAL_BLOCKERS
    build_log_excerpt = extract_build_log_excerpt(eval_result.build_log)

    # Architectural additions: build progress + root cause + relaxation
    progress = estimate_build_progress(eval_result.build_log)
    root_causes = extract_root_cause_details(
        eval_result.error_summary, eval_result.build_log,
    )
    relax_flags = suggest_relaxation_flags(error_class, progress)

    # Enrich fix suggestion with root-cause specifics
    if root_causes:
        entity_summary = "; ".join(str(rc) for rc in root_causes[:3])
        fix_suggestion += f"\n\nSpecific entities involved: {entity_summary}"

    if relax_flags:
        flag_str = " ".join(relax_flags)
        fix_suggestion += (
            f"\n\nConsider adding these Maven flags to skip optional phases: {flag_str}"
        )

    return AnalysisResult(
        error_class=error_class,
        error_summary=eval_result.error_summary,
        fix_suggestion=fix_suggestion,
        is_fundamental_blocker=is_blocker,
        build_log_excerpt=build_log_excerpt,
        build_progress=progress,
        root_cause_details=root_causes,
        relaxation_flags=relax_flags,
    )


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


ANALYZE_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "responsible_agent": {"type": "string"},
        "playbook_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_type": {"type": "string", "enum": ["DO", "DONT"]},
                    "rule": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["rule_type", "rule", "reasoning"],
            },
        },
        "spec_overrides": {"type": "object"},
        "is_systemic": {"type": "boolean"},
    },
    "required": ["root_cause", "responsible_agent", "playbook_updates", "spec_overrides", "is_systemic"],
}

ANALYZE_AGENT_SYSTEM = """\
You are the AnalyzeAgent for the buildroot reconstruction pipeline. After each failed \
build iteration, you receive the build logs from all candidate builds and must:

1. Diagnose the root cause of the failure
2. Identify which node agent (jdk, image, tag, build_cmd, repo, etc.) is responsible
3. Write playbook rules (DO/DON'T) for future iterations
4. Suggest spec_overrides — field-level overrides for the next observe() cycle
5. Flag systemic issues that won't be fixed by iterating

## Valid spec_overrides field names

You MUST use ONLY these exact field names in spec_overrides. Do NOT invent field names \
like 'jdk_image', 'repo_url', 'repo_tag', 'pre_build_steps', or 'source_setup'.

- base_image (or image): Docker base image, e.g. 'eclipse-temurin:17-jdk'
- jdk_version: JDK version string, e.g. '17', '11', '8'
- jdk_distribution: JDK distribution, e.g. 'temurin', 'openjdk'
- build_command (or build_cmd): main build command, e.g. 'mvn clean install -B', 'ant jar', 'gradle build'
- maven_version: Maven version string, e.g. '3.9.6'
- git_tag (or tag, source_tag): git tag to clone
- source_repo: git repository URL
- system_package: space-separated apt packages to install (replaces existing list)
- extra_packages (or apt_packages): additional apt packages to append
- image_setup_cmds (or pre_build_cmds): list of commands to run before the main build
- pre_build_cmd: single command to prepend before the main build

Output structured JSON with root_cause, responsible_agent, playbook_updates, \
spec_overrides (field_name -> value), and is_systemic flag.
"""


@dataclass
class AnalyzeAgentResult:
    root_cause: str = ""
    responsible_agent: str = ""
    playbook_updates: list[dict[str, str]] = field(default_factory=list)
    spec_overrides: dict[str, Any] = field(default_factory=dict)
    is_systemic: bool = False


class AnalyzeAgent:
    """Per-cycle analysis agent — Claude Code subprocess that diagnoses failures."""

    def __init__(self, playbook_dir: str = ".factory/playbooks/node_agents") -> None:
        self._playbook_dir = Path(playbook_dir)

    def analyze_cycle(
        self,
        coordinate: str,
        build_results: list[dict[str, Any]],
        iteration: int,
        dead_ends: list[DeadEndEntry],
    ) -> AnalyzeAgentResult:
        results_summary = json.dumps(build_results[:5], indent=2, default=str)[:4000]
        dead_end_summary = "\n".join(
            f"- [{de.error_class}] {de.approach} (failed {de.failure_count}x)"
            for de in dead_ends if de.is_exhausted
        ) or "None exhausted."

        task = f"""\
Analyze the failed build iteration {iteration} for {coordinate}.

## Build Results (up to K candidates)
{results_summary}

## Dead-End Registry
{dead_end_summary}

Diagnose the root cause, identify the responsible node agent, and propose:
1. Playbook DO/DON'T rules for future iterations
2. spec_overrides (field_name -> new_value) to try in the next observe() cycle
3. Whether this is a systemic issue that won't improve with iteration
"""

        agent_result = spawn_claude_agent(
            task=task,
            system_prompt=ANALYZE_AGENT_SYSTEM,
            model="claude-sonnet-4-6",
            json_schema=ANALYZE_AGENT_SCHEMA,
            max_turns=3,
            max_budget_usd=2.0,
            timeout=300,
            disallowed_tools=["Bash", "Read", "Edit", "Write", "WebSearch", "WebFetch", "Agent"],
        )

        if agent_result.is_error:
            logger.warning("AnalyzeAgent failed: %s", agent_result.error_message)
            return AnalyzeAgentResult()

        return self._parse_result(agent_result)

    def _parse_result(self, agent_result) -> AnalyzeAgentResult:
        output = agent_result.structured_output
        if not output:
            return AnalyzeAgentResult()

        result = AnalyzeAgentResult(
            root_cause=output.get("root_cause", ""),
            responsible_agent=output.get("responsible_agent", ""),
            playbook_updates=output.get("playbook_updates", []),
            spec_overrides=output.get("spec_overrides", {}),
            is_systemic=output.get("is_systemic", False),
        )

        if result.playbook_updates:
            self._update_playbook(result.responsible_agent, result.playbook_updates)

        return result

    def _update_playbook(self, agent_name: str, updates: list[dict[str, str]]) -> None:
        self._playbook_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", agent_name)
        if not safe_name:
            safe_name = "unknown"
        playbook_path = self._playbook_dir / f"{safe_name}.md"

        existing = ""
        if playbook_path.exists():
            existing = playbook_path.read_text()

        new_entries = []
        for update in updates:
            rule_type = update.get("rule_type", "DO")
            rule = update.get("rule", "")
            reasoning = update.get("reasoning", "")
            entry = f"- [{rule_type}] {rule} — {reasoning} (helpful=0, harmful=0)"
            if entry not in existing:
                new_entries.append(entry)

        if new_entries:
            with open(playbook_path, "a") as f:
                for entry in new_entries:
                    f.write(entry + "\n")
            logger.info(
                "AnalyzeAgent wrote %d playbook entries for %s",
                len(new_entries), agent_name,
            )

    def read_playbook(self, agent_name: str) -> str:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", agent_name)
        if not safe_name:
            safe_name = "unknown"
        playbook_path = self._playbook_dir / f"{safe_name}.md"
        if playbook_path.exists():
            return playbook_path.read_text()
        return ""


def _suggest_fix(error_class: str, error_summary: str) -> str:
    """Suggest a fix direction based on the error class."""
    suggestions = {
        "containerfile/parse_error": (
            "The Containerfile is malformed — it must start with a FROM instruction "
            "(optionally preceded by ARG). Regenerate the Containerfile from scratch "
            "ensuring the first non-comment line is FROM."
        ),
        "build_tool/wrong_build_system": (
            "This project uses Gradle, not Maven. Switch the build command to use "
            "'./gradlew build' or install Gradle in the Containerfile. "
            "If the pom.xml is in a subdirectory, add WORKDIR to the correct path."
        ),
        "dependency_resolution/missing_artifact": (
            "Try a different Maven repository or check if the dependency version exists. "
            "Consider adding -U to force snapshot updates."
        ),
        "dependency_resolution/version_conflict": (
            "Check dependency management section. Try using -Denforcer.skip=true."
        ),
        "compilation/jdk_mismatch": (
            "Switch to the correct JDK version. Check the pom.xml for "
            "maven.compiler.source/target properties."
        ),
        "compilation/syntax_error": (
            "This may indicate a generated-source issue. Check if annotation "
            "processors need to run first."
        ),
        "plugin/configuration_error": (
            "Try skipping the failing plugin with -Dplugin.skip=true or "
            "updating the plugin version."
        ),
        "plugin/gpg_error": "Add -Dgpg.skip=true to the build command.",
        "environment/gha_secrets": (
            "Remove ${{ secrets.* }} expressions from ARG/ENV lines."
        ),
        "environment/gha_expressions": (
            "Remove all ${{ }} expressions — they are GitHub Actions syntax, "
            "not valid in Containerfiles."
        ),
        "environment/image_resolution": (
            "Use fully-qualified image names with docker.io/ prefix."
        ),
        "source/wrong_tag": (
            "Try alternate tag formats: remove 'v' prefix, try 'rel/' prefix, "
            "or use the branch name."
        ),
        "source/clone_failed": "The repository may be private or have moved.",
        "build_tool/multi_module": (
            "Add '-pl <module>' flag to build only the target module, "
            "or 'mvn install -N' to install parent first."
        ),
        "build_tool/maven_wrapper": (
            "Use 'mvn' instead of './mvnw', or ensure mvnw is executable "
            "(chmod +x mvnw)."
        ),
        "resource/oom": (
            "Increase Java heap: ENV MAVEN_OPTS='-Xmx2g' or use -Dmaven.compiler.fork=false."
        ),
        "resource/disk_space": "Use a smaller base image or multi-stage build.",
        "environment/credentials": "This package requires authentication — likely a private repo.",
        "environment/obsolete_jvm_flag": (
            "The build uses obsolete JVM flags (e.g. MaxPermSize, PermSize) removed in JDK 9+. "
            "Remove them via sed in the Containerfile before building: "
            "sed -i 's/-XX:MaxPermSize=[^ ]*//' or use JDK 8 if the project supports it."
        ),
        "l3/jar_not_found": (
            "Build completed but no JAR was produced in target/. Check if this is a Gradle "
            "project (outputs to build/libs/) or a multi-module project (JARs in */target/). "
            "Ensure the build command produces a JAR (not just compiles)."
        ),
        "l4/structural_divergence": (
            "JAR structure differs from the original — files are missing or extra. "
            "Check if resource filtering, shading, or assembly plugins are configured correctly. "
            "Add SOURCE_DATE_EPOCH=0 and -Dproject.build.outputTimestamp=1980-01-01T00:00:00Z."
        ),
        "l4/metadata_mismatch": (
            "JAR metadata (MANIFEST.MF, pom.properties) differs. Ensure SOURCE_DATE_EPOCH=0 "
            "is set, add -Dproject.build.outputTimestamp=1980-01-01T00:00:00Z, and strip "
            "non-reproducible entries (Built-By, Build-Jdk, Created-By) from MANIFEST.MF."
        ),
        "l4/bytecode_divergence": (
            "Compiled class files differ from the original. This may be caused by a different "
            "JDK version/vendor, annotation processor differences, or compiler flag mismatches. "
            "Verify JDK version exactly matches the original build environment."
        ),
    }
    return suggestions.get(error_class, "Analyze the build log for specific failure details.")
