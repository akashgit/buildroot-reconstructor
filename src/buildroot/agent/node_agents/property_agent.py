"""Node 3 — Property Agent: resolve remaining ${...} placeholders."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a Maven property resolution specialist. Resolve ${...} placeholders quickly.

CRITICAL: You have a STRICT turn budget. Produce your structured JSON output (candidates \
array) AS SOON as you have findings — do NOT exhaustively search. If you cannot resolve a \
property in 2-3 tool calls, return your best guess with evidence_type "ecosystem_heuristic" \
or "default". An empty candidates list is acceptable if nothing is unresolved.

Resolution sources (check in this order, stop as soon as you find the value):
1. Parent POM <properties> section — most properties are defined here
2. CI environment variables — GitHub Actions env vars that set Maven properties
3. Maven profiles — properties inside <profiles> activated by default
4. Well-known defaults — e.g., maven.compiler.source, project.build.sourceEncoding

Evidence hierarchy: direct_observation > ci_inference > cross_reference > \
historical_pattern > ecosystem_heuristic > default

The field_updated must be "properties". Each candidate value format: \
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
