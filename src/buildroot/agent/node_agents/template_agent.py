"""Node 10 — Template Agent: Containerfile syntax validation, unresolved placeholder detection."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a Containerfile template reviewer for the buildroot reconstruction pipeline.

Your job: validate the rendered Containerfile for correctness before it goes to build. \
This is the last gate before the Containerfile is emitted.

Key checks:
1. **Syntax validation** — every line must be a valid Dockerfile instruction or continuation
2. **Unresolved placeholders** — detect any remaining ${...} that should have been resolved
3. **Missing package installs** — check if required packages are installed (git, curl, etc.)
4. **Image references** — verify FROM image references are valid
5. **Build command** — verify the RUN build command matches the detected build system
6. **Working directory** — verify WORKDIR is correct, especially for multi-module projects

Review the Containerfile line by line and identify any issues. For each issue, propose \
the corrected line or section.

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "containerfile". Each candidate's value should describe \
the fix needed (e.g., "fix_from:eclipse-temurin:17-jdk" or "fix_workdir:/build/submodule" \
or "fix_build_cmd:./gradlew build -x test" or "valid" if no issues found).
"""


class TemplateAgent(NodeAgent):
    node_name = "template_agent"
    field_name = "containerfile"
    system_prompt = SYSTEM_PROMPT

    def should_activate(self, gap_report, spec_overrides=None) -> bool:
        return True

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        containerfile = context.get("containerfile", "")
        subdir = spec.pom_data.properties.get("_buildroot_subdir", "")

        return (
            f"Review this rendered Containerfile for correctness.\n\n"
            f"Artifact: {spec.pom_data.group_id}:{spec.pom_data.artifact_id}:{spec.pom_data.version}\n"
            f"Source repo: {spec.source_repo}\n"
            f"Git tag: {spec.git_tag}\n"
            f"Build commands: {spec.build_commands}\n"
            f"Subdirectory: {subdir}\n"
            f"Modules: {spec.pom_data.modules}\n\n"
            f"--- Containerfile ---\n{containerfile}\n--- End ---\n\n"
            f"Check for:\n"
            f"1. Unresolved ${{...}} placeholders\n"
            f"2. Invalid FROM image references\n"
            f"3. Missing WORKDIR for multi-module projects (should cd into {subdir or 'N/A'})\n"
            f"4. Wrong build command (Maven vs Gradle)\n"
            f"5. Missing required packages"
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        value = candidate.value
        if value.startswith("fix_from:"):
            spec.jdk_spec.base_image = value.split(":", 1)[1].strip()
        elif value.startswith("fix_workdir:"):
            subdir = value.split(":", 1)[1].strip()
            spec.pom_data.properties["_buildroot_subdir"] = subdir
        elif value.startswith("fix_build_cmd:"):
            cmd = value.split(":", 1)[1].strip()
            spec.build_commands = [cmd]
