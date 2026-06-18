"""Node 3 — Property Agent: resolve remaining ${...} placeholders."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a Maven property resolution specialist for the buildroot reconstruction pipeline.

Your job: resolve any remaining ${...} placeholders in the spec's properties that the \
deterministic resolver could not handle. Sources to check:
1. **CI environment variables** — GitHub Actions, Jenkins, CircleCI env vars that set Maven properties
2. **Maven profiles** — properties defined inside <profiles> that may be activated by default
3. **Project documentation** — README, BUILDING.md for build-time property requirements
4. **Well-known properties** — common Maven properties like project.build.sourceEncoding

You have access to Read, Bash, and WebSearch tools. Use them to:
- Search the source repository for property definitions in CI configs
- Check pom.xml profiles for auto-activated properties
- Look up well-known property defaults

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "properties". Each candidate's value should be in the format \
"property.name=resolved.value" (e.g., "maven.compiler.source=17").
"""


class PropertyAgent(NodeAgent):
    node_name = "property_agent"
    field_name = "property"
    system_prompt = SYSTEM_PROMPT

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        unresolved = {}
        for key, value in spec.pom_data.properties.items():
            if "${" in str(value):
                unresolved[key] = value

        if not unresolved:
            return "No unresolved properties found. Return an empty candidates list."

        ci_env = {}
        if spec.ci_data:
            ci_env = spec.ci_data.env_vars

        return (
            f"Resolve these unresolved Maven properties.\n\n"
            f"Artifact: {spec.pom_data.group_id}:{spec.pom_data.artifact_id}:{spec.pom_data.version}\n"
            f"Source repo: {spec.source_repo}\n\n"
            f"Unresolved properties:\n"
            + "\n".join(f"  {k} = {v}" for k, v in unresolved.items())
            + "\n\nCI environment variables:\n"
            + "\n".join(f"  {k} = {v}" for k, v in ci_env.items())
            + "\n\nSearch the source repo and CI configs for these property values."
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        if "=" in candidate.value:
            key, _, value = candidate.value.partition("=")
            key = key.strip()
            value = value.strip()
            if key in spec.pom_data.properties:
                spec.pom_data.properties[key] = value
