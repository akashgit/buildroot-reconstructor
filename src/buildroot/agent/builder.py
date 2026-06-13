"""Builder agent — LLM-driven Containerfile mutation with three modes."""

from __future__ import annotations

import logging
import re

from anthropic import AnthropicVertex

from buildroot.agent.models import DeadEndEntry
from buildroot.pipeline.models import BuildrootSpec

logger = logging.getLogger(__name__)

GHA_EXPRESSION_RE = re.compile(r"\$\{\{[^}]*\}\}")

DEFAULT_MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """\
You are an expert at writing Containerfiles (Dockerfiles) for reproducible Maven builds.

Your task: given a Containerfile that failed to build, plus the error analysis, produce a \
corrected Containerfile that fixes the identified issue.

Rules:
- Output ONLY the corrected Containerfile content, nothing else
- Do NOT include markdown code fences
- Do NOT use GitHub Actions expressions (${{ ... }}) — they don't work in Containerfiles
- Do NOT repeat approaches listed in the dead-end registry
- Preserve the overall structure (FROM, JDK install, Maven install, git clone, build)
- Use fully-qualified image names (e.g. docker.io/library/maven:3.9-eclipse-temurin-17)
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


class Builder:
    """LLM-driven Containerfile generation and mutation."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self._client = AnthropicVertex(
            region="us-east5", project_id="itpc-gcp-ai-eng-claude"
        )
        self._model = model

    def _call_llm(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return text

    def refine(
        self,
        containerfile: str,
        error_class: str,
        error_summary: str,
        dead_ends: list[DeadEndEntry],
        spec: BuildrootSpec,
    ) -> str:
        """Exploit mode: targeted fix based on error analysis."""
        prompt = f"""\
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
{_format_spec_metadata(spec)}

Produce the corrected Containerfile with a targeted fix for the identified error."""

        result = self._call_llm(prompt)
        return sanitize_gha_expressions(result)

    def explore(
        self,
        containerfile: str,
        spec: BuildrootSpec,
        error_class: str,
        error_summary: str,
        dead_ends: list[DeadEndEntry],
    ) -> str:
        """Explore mode: fundamentally different approach."""
        prompt = f"""\
The current Containerfile approach is not working. Take a fundamentally different approach.

## Current Containerfile (NOT WORKING — try something different)
{containerfile}

## Error History
Error class: {error_class}
Last error: {error_summary}

## Dead-End Registry (DO NOT retry these)
{_format_dead_ends(dead_ends)}

## Package Metadata
{_format_spec_metadata(spec)}

Try a completely different strategy:
- Different base image (e.g. switch from JDK-specific to ubuntu + manual JDK install, or vice versa)
- Different Maven installation method
- Different build flags or approach
- Different git checkout strategy

Produce a new Containerfile using a fundamentally different approach."""

        result = self._call_llm(prompt)
        return sanitize_gha_expressions(result)

    def fresh_start(self, spec: BuildrootSpec) -> str:
        """Meta-shift mode: regenerate from metadata only, ignoring prior attempts."""
        prompt = f"""\
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

        result = self._call_llm(prompt)
        return sanitize_gha_expressions(result)
