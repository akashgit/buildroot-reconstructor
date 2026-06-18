"""Builder agent — Claude Code subprocess-driven Containerfile mutation with three modes."""

from __future__ import annotations

import logging
import re

from buildroot.agent.analyzer import (
    BUILD_PHASES,
    BuildProgress,
    compute_progress_delta,
    detect_error_loop,
    estimate_build_progress,
    extract_root_cause_details,
    suggest_relaxation_flags,
)
from buildroot.agent.claude_runner import AgentResult, spawn_claude_agent
from buildroot.agent.models import DeadEndEntry
from buildroot.pipeline.models import BuildrootSpec

logger = logging.getLogger(__name__)

GHA_EXPRESSION_RE = re.compile(r"\$\{\{[^}]*\}\}")
# Matches fenced code blocks (```dockerfile ... ``` or ``` ... ```)
_CODE_FENCE_RE = re.compile(
    r"```(?:dockerfile|Dockerfile|docker)?\s*\n(.*?)```", re.DOTALL
)
# Valid Dockerfile instruction prefixes (case-insensitive check done via .upper())
_DOCKERFILE_INSTRUCTIONS = frozenset({
    "FROM", "RUN", "COPY", "ADD", "ENV", "ARG", "WORKDIR", "EXPOSE",
    "CMD", "ENTRYPOINT", "LABEL", "USER", "VOLUME", "SHELL", "HEALTHCHECK",
    "ONBUILD", "STOPSIGNAL", "MAINTAINER",
})

DEFAULT_MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """\
You are an expert at writing Containerfiles (Dockerfiles) for reproducible Java builds.

Your task: given a Containerfile that failed to build, plus the error analysis, produce a \
corrected Containerfile that fixes the identified issue.

Rules:
- Output ONLY the corrected Containerfile content, nothing else
- Do NOT include markdown code fences or explanatory prose — raw Containerfile lines ONLY
- Do NOT use GitHub Actions expressions (${{ ... }}) — they don't work in Containerfiles
- Do NOT repeat approaches listed in the dead-end registry
- Preserve the overall structure (FROM, JDK install, build tool install, git clone, build)
- Use fully-qualified image names (e.g. docker.io/library/maven:3.9-eclipse-temurin-17)
- Always add -Dproject.build.outputTimestamp=1 to Maven build commands for reproducible builds
- Some projects use Gradle (build.gradle / gradlew) instead of Maven. Detect the build \
system from the repository contents and use the appropriate tool (./gradlew, gradle, or mvn).

Strategy guidance:
- When a build fails at plugin execution, consider adding -D<plugin>.skip=true flags \
to bypass optional enforcement/checking plugins (checkstyle, enforcer, animal-sniffer, \
javadoc, pmd, spotbugs, gpg, jacoco, rat)
- When the build reaches compilation but fails, check whether annotation processors \
or code generators need specific setup
- When dependency resolution fails, try adding -U to force updates, or check if a \
parent POM needs to be installed first with 'mvn install -N'
- When stuck at the same phase for multiple attempts, escalate: skip more optional \
phases or try a fundamentally different base image / build approach
- Pay attention to the build progress indicator — if the build is getting further, \
the current direction is correct; if regressing, revert the last change
"""

DIAGNOSIS_PROMPT = """\
You are an expert Java build diagnostician. Given a failed Containerfile build, \
analyze the root cause precisely and produce a specific fix plan.

Your diagnosis must include:
1. WHAT specifically is failing (exact artifact, class, plugin, or phase)
2. WHY it is failing (version mismatch, missing dependency, wrong JDK, etc.)
3. WHAT the fix should be (specific, actionable changes — not vague suggestions)
4. HOW the fix differs from previously attempted dead-end approaches

Be concrete and specific. Reference exact error messages and entity names.
"""


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


def _format_dead_ends(dead_ends: list[DeadEndEntry]) -> str:
    if not dead_ends:
        return "None yet."
    parts = []
    for de in dead_ends:
        if de.is_exhausted:
            parts.append(
                f"- [{de.error_class}] {de.approach} "
                f"(failed {de.failure_count}x — DO NOT retry)"
            )
    return "\n".join(parts) if parts else "None exhausted yet."


def _format_spec_metadata(spec: BuildrootSpec) -> str:
    parts = [
        f"Source repo: {spec.source_repo}",
        f"Git tag: {spec.git_tag}",
        f"JDK: {spec.jdk_spec.version} ({spec.jdk_spec.distribution})",
        f"Maven version: {spec.maven_version or 'default'}",
        f"Build commands: {spec.build_commands}",
    ]
    if spec.pom_data.modules:
        parts.append(f"Modules: {spec.pom_data.modules}")
    return "\n".join(parts)


def _extract_containerfile(agent_result: AgentResult) -> str:
    """Extract Containerfile content from agent output, stripping markdown fences.

    Uses multiple strategies to handle prose-wrapped responses:
    1. Regex to find fenced code blocks anywhere in the text
    2. Scan for the first FROM line and extract from there
    3. Fall back to the original text-stripping approach
    """
    text = agent_result.text.strip()

    # Strategy 1: Extract content from fenced code blocks anywhere in the text
    fence_matches = list(_CODE_FENCE_RE.finditer(text))
    if fence_matches:
        # Pick the longest fenced block (most likely the full Containerfile)
        best = max(fence_matches, key=lambda m: len(m.group(1)))
        extracted = best.group(1).strip()
        if extracted:
            return extracted

    # Strategy 2: Legacy — if the whole text starts with a fence, strip it
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text:
            return text

    # Strategy 3: Find the first FROM line and keep only valid Dockerfile instruction lines
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith("FROM "):
            candidate_lines: list[str] = []
            in_continuation = False
            for raw_line in lines[i:]:
                s = raw_line.strip()
                # Allow blank lines between instructions
                if not s:
                    candidate_lines.append(raw_line)
                    in_continuation = False
                    continue
                # Allow comments
                if s.startswith("#"):
                    candidate_lines.append(raw_line)
                    in_continuation = False
                    continue
                # Continuation of previous line (previous line ended with \)
                if in_continuation:
                    candidate_lines.append(raw_line)
                    in_continuation = s.endswith("\\")
                    continue
                # Check if line starts with a valid Dockerfile instruction
                first_word = s.split()[0].upper() if s.split() else ""
                if first_word in _DOCKERFILE_INSTRUCTIONS:
                    candidate_lines.append(raw_line)
                    in_continuation = s.endswith("\\")
                    continue
                # Not a valid instruction — stop (prose detected)
                break
            # Remove trailing blank lines
            while candidate_lines and not candidate_lines[-1].strip():
                candidate_lines.pop()
            extracted = "\n".join(candidate_lines).strip()
            if extracted:
                return extracted

    return text


def _validate_containerfile(candidate: str, fallback: str) -> str:
    """Validate that a Containerfile candidate is structurally sound.

    Requires BOTH a FROM instruction AND at least one body instruction (RUN/COPY/ADD).
    This filters out prose-wrapped responses that happen to start with FROM but lack
    actual build steps.

    Returns the candidate if valid, otherwise the fallback (previous known-good).
    """
    if not candidate or not candidate.strip():
        logger.warning("Empty Containerfile candidate — using fallback")
        return fallback

    has_from = False
    has_body_instruction = False
    _body_prefixes = ("RUN ", "COPY ", "ADD ")

    for line in candidate.splitlines():
        stripped = line.strip()
        # Skip comments and blank lines
        if not stripped or stripped.startswith("#"):
            continue
        upper = stripped.upper()
        if not has_from:
            if upper.startswith("FROM "):
                has_from = True
                continue
            # ARG before FROM is valid in Dockerfiles
            if upper.startswith("ARG "):
                continue
            # First non-comment, non-ARG line is not FROM — invalid
            break
        # After FROM, look for body instructions
        if any(upper.startswith(p) for p in _body_prefixes):
            has_body_instruction = True
            break

    if has_from and has_body_instruction:
        return candidate

    reason = "missing FROM instruction" if not has_from else "missing body instructions (RUN/COPY/ADD)"
    logger.warning(
        "Containerfile candidate %s — using fallback. First 200 chars: %s",
        reason, candidate[:200],
    )
    return fallback if fallback.strip() else candidate


class Builder:
    """Claude Code subprocess-driven Containerfile generation and mutation.

    The builder is **stateful** — it tracks error history and build progress
    across iterations so it can self-diagnose and adapt its strategy even
    when the caller doesn't pass rich remediation context.
    """

    def __init__(
        self, model: str = DEFAULT_MODEL, meta_guidance: str | None = None
    ) -> None:
        self._model = model
        self._meta_guidance = meta_guidance
        # Iteration state for adaptive behaviour
        self._error_history: list[str] = []
        self._iteration_count: int = 0
        self._last_progress: BuildProgress | None = None
        self._best_progress_index: int = -1

    def _build_system_prompt(self) -> str:
        system = SYSTEM_PROMPT
        if self._meta_guidance:
            system = self._meta_guidance + "\n\n" + system
        return system

    # ------------------------------------------------------------------
    # Internal helpers for self-diagnosis
    # ------------------------------------------------------------------

    def _track_iteration(
        self, error_class: str, error_summary: str, build_log: str = "",
    ) -> BuildProgress:
        """Record iteration state and return current build progress."""
        self._iteration_count += 1
        self._error_history.append(error_class)

        progress = estimate_build_progress(build_log or error_summary)
        if progress.phase_index > self._best_progress_index:
            self._best_progress_index = progress.phase_index

        return progress

    def _compute_internal_remediation(
        self,
        error_class: str,
        error_summary: str,
        build_log: str = "",
    ) -> str:
        """Compute remediation context internally using analyzer utilities.

        This bridges the gap when the caller does not supply
        ``remediation_context`` — the builder generates its own.
        """
        progress = estimate_build_progress(build_log or error_summary)
        root_causes = extract_root_cause_details(error_summary, build_log)
        relax_flags = suggest_relaxation_flags(error_class, progress)
        is_loop, loop_desc = detect_error_loop(self._error_history)

        sections: list[str] = []

        # Build progress
        sections.append(f"## Build Progress\n{progress.description}")
        if self._last_progress is not None:
            delta = compute_progress_delta(progress, self._last_progress)
            sections.append(f"## Progress Delta\n{delta}")

        # Root cause
        if root_causes:
            rc_lines = [str(rc) for rc in root_causes[:5]]
            sections.append(
                "## Root Cause Details\n" + "\n".join(f"- {line}" for line in rc_lines)
            )

        # Relaxation flags
        if relax_flags:
            sections.append(
                "## Suggested Build Flags\n"
                f"Consider adding: {' '.join(relax_flags)}"
            )

        # Error loop warning
        if is_loop:
            sections.append(
                f"## ⚠ ERROR LOOP DETECTED\n{loop_desc}\n"
                "You MUST take a fundamentally different approach."
            )
        elif len(self._error_history) >= 2:
            recent = self._error_history[-5:]
            sections.append(f"## Error Trajectory\n{' → '.join(recent)}")

        # Update state for next iteration
        self._last_progress = progress

        return "\n\n".join(sections)

    def diagnose(
        self,
        containerfile: str,
        error_class: str,
        error_summary: str,
        dead_ends: list[DeadEndEntry],
        spec: BuildrootSpec,
    ) -> str:
        """Phase 1 of two-phase approach: produce a structured diagnosis and fix plan.

        Spawns a lightweight agent (fewer turns, lower budget) to reason about
        the root cause before the fix is generated. Returns the diagnosis text.
        """
        root_causes = extract_root_cause_details(error_summary, "")
        rc_block = "\n".join(f"- {rc}" for rc in root_causes) if root_causes else "None extracted"

        task = f"""\
Analyze this Containerfile build failure and produce a specific fix plan.

## Current Containerfile
{containerfile}

## Error Classification: {error_class}

## Build Error
{error_summary}

## Root Cause Entities
{rc_block}

## Dead-End Registry (approaches that already failed — do NOT suggest these)
{_format_dead_ends(dead_ends)}

## Package Metadata
{_format_spec_metadata(spec)}

Produce a diagnosis with:
1. WHAT specifically is failing and WHY
2. WHAT the fix should be (specific Containerfile changes)
3. WHY this fix is different from dead-end approaches listed above"""

        agent_result = spawn_claude_agent(
            task=task,
            system_prompt=DIAGNOSIS_PROMPT,
            model=self._model,
            max_turns=8,
            max_budget_usd=1.0,
            timeout=180,
        )

        if agent_result.is_error:
            logger.warning("Diagnosis agent failed: %s", agent_result.error_message)
            return ""

        return agent_result.text.strip()

    def refine(
        self,
        containerfile: str,
        error_class: str,
        error_summary: str,
        dead_ends: list[DeadEndEntry],
        spec: BuildrootSpec,
        *,
        remediation_context: str | None = None,
    ) -> str:
        """Exploit mode: targeted fix based on error analysis.

        When the caller doesn't supply ``remediation_context``, the builder
        computes its own from internal state and analyzer utilities.
        When the same error class has been seen 2+ times, a lightweight
        diagnosis agent runs first (two-phase approach).
        """
        # Track iteration state
        self._track_iteration(error_class, error_summary)

        # Compute remediation context if the caller didn't provide one
        if not remediation_context:
            remediation_context = self._compute_internal_remediation(
                error_class, error_summary,
            )

        # Two-phase: diagnose first when we've seen this error class before
        diagnosis_block = ""
        same_class_count = self._error_history.count(error_class)
        if same_class_count >= 2:
            logger.info(
                "Error class '%s' seen %dx — running diagnosis agent",
                error_class, same_class_count,
            )
            diagnosis = self.diagnose(
                containerfile, error_class, error_summary, dead_ends, spec,
            )
            if diagnosis:
                diagnosis_block = f"\n\n## Expert Diagnosis\n{diagnosis}"

        remediation_block = ""
        if remediation_context:
            remediation_block = f"\n\n## Remediation Context\n{remediation_context}"

        task = f"""\
Fix the following Containerfile build failure.

## Current Containerfile
{containerfile}

## Error Classification
{error_class}

## Build Error (key lines)
{error_summary}

## Dead-End Registry (DO NOT retry these)
{_format_dead_ends(dead_ends)}

## Package Metadata
{_format_spec_metadata(spec)}{remediation_block}{diagnosis_block}

Produce the corrected Containerfile with a targeted fix for the identified error."""

        agent_result = spawn_claude_agent(
            task=task,
            system_prompt=self._build_system_prompt(),
            model=self._model,
            max_turns=15,
            max_budget_usd=5.0,
            timeout=600,
        )

        if agent_result.is_error:
            logger.error("Builder refine failed: %s", agent_result.error_message)
            return containerfile

        result = _extract_containerfile(agent_result)
        result = sanitize_gha_expressions(result)
        return _validate_containerfile(result, containerfile)

    def explore(
        self,
        containerfile: str,
        spec: BuildrootSpec,
        error_class: str,
        error_summary: str,
        dead_ends: list[DeadEndEntry],
        *,
        remediation_context: str | None = None,
    ) -> str:
        """Explore mode: fundamentally different approach.

        Uses internal state to provide build-progress context and error
        trajectory even when the caller doesn't supply remediation_context.
        """
        # Track iteration state
        self._track_iteration(error_class, error_summary)

        # Compute remediation context if not provided
        if not remediation_context:
            remediation_context = self._compute_internal_remediation(
                error_class, error_summary,
            )

        remediation_block = ""
        if remediation_context:
            remediation_block = f"\n\n## Analysis of Why Current Approach Fails\n{remediation_context}"

        # Build a trajectory summary for the explore prompt
        trajectory_block = ""
        if len(self._error_history) >= 2:
            recent = self._error_history[-5:]
            trajectory_block = (
                f"\n\nError trajectory across iterations: {' → '.join(recent)}"
            )
            if self._best_progress_index >= 0:
                best_phase = BUILD_PHASES[self._best_progress_index] if self._best_progress_index < len(BUILD_PHASES) else "unknown"
                trajectory_block += (
                    f"\nBest build progress ever reached: '{best_phase}' phase"
                )

        task = f"""\
The current Containerfile approach is not working. Take a fundamentally different approach.

## Current Containerfile (NOT WORKING — try something different)
{containerfile}

## Error History
Error class: {error_class}
Last error: {error_summary}{trajectory_block}

## Dead-End Registry (DO NOT retry these)
{_format_dead_ends(dead_ends)}

## Package Metadata
{_format_spec_metadata(spec)}{remediation_block}

Try a completely different strategy:
- Different base image (e.g. switch from JDK-specific to ubuntu + manual JDK install, or vice versa)
- Different Maven installation method
- Different build flags or approach
- Different git checkout strategy

Produce a new Containerfile using a fundamentally different approach."""

        agent_result = spawn_claude_agent(
            task=task,
            system_prompt=self._build_system_prompt(),
            model=self._model,
            max_turns=15,
            max_budget_usd=5.0,
            timeout=600,
        )

        if agent_result.is_error:
            logger.error("Builder explore failed: %s", agent_result.error_message)
            return containerfile

        result = _extract_containerfile(agent_result)
        result = sanitize_gha_expressions(result)
        return _validate_containerfile(result, containerfile)

    def fresh_start(self, spec: BuildrootSpec) -> str:
        """Meta-shift mode: regenerate from metadata only, ignoring prior attempts."""
        task = f"""\
Generate a Containerfile from scratch for this Maven package. Ignore any prior attempts.

## Package Metadata
{_format_spec_metadata(spec)}

## Requirements
- Use a JDK {spec.jdk_spec.version} base image (prefer eclipse-temurin)
- Install Maven {spec.maven_version or '3.9.6'}
- Clone the source from {spec.source_repo} at tag {spec.git_tag}
- Run the build command(s): {spec.build_commands}
- The built artifact should be a JAR in the target/ directory
- Use fully-qualified image names (docker.io/...)
- Do NOT use GitHub Actions expressions (${{{{ ... }}}})

Produce a complete Containerfile."""

        agent_result = spawn_claude_agent(
            task=task,
            system_prompt=self._build_system_prompt(),
            model=self._model,
            max_turns=15,
            max_budget_usd=5.0,
            timeout=600,
        )

        if agent_result.is_error:
            logger.error("Builder fresh_start failed: %s", agent_result.error_message)
            return ""

        result = _extract_containerfile(agent_result)
        result = sanitize_gha_expressions(result)
        return _validate_containerfile(result, "")
