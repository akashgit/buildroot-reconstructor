"""Node 1 — POM Agent: relocation detection, sparse POM detection."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a Maven POM reviewer for the buildroot reconstruction pipeline.

Your job: given a parsed POM's data, detect issues that would break the build:
1. **Relocation detection** — check if the POM contains <distributionManagement><relocation> \
elements pointing to different coordinates. If so, return the correct groupId:artifactId.
2. **Sparse POM detection** — check if the POM is a "sparse" POM (no real content, only a \
parent reference or a relocation stub). If so, flag it.
3. **Packaging type** — verify the packaging type is appropriate (jar, pom, bundle, war).

You have access to Read, Bash, and WebSearch tools. Use them to:
- Fetch the raw POM XML from Maven Central if needed
- Check for relocation elements
- Verify packaging type

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "pom_data" and each candidate's value should describe the finding \
(e.g., "relocated:new.group:new.artifact" or "valid" if no issues found).
"""


class PomAgent(NodeAgent):
    node_name = "pom_agent"
    field_name = "pom_data"
    system_prompt = SYSTEM_PROMPT

    def should_activate(self, gap_report) -> bool:
        return True

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        pom = spec.pom_data
        props_sample = dict(list(pom.properties.items())[:20])
        return (
            f"Review this POM data for relocation or sparse POM issues.\n\n"
            f"Group ID: {pom.group_id}\n"
            f"Artifact ID: {pom.artifact_id}\n"
            f"Version: {pom.version}\n"
            f"Packaging: {pom.packaging}\n"
            f"Modules: {pom.modules}\n"
            f"Parent chain length: {len(pom.parent_chain)}\n"
            f"Properties count: {len(pom.properties)}\n"
            f"Properties sample: {props_sample}\n"
            f"SCM: {pom.scm}\n"
            f"URL: {pom.url}\n\n"
            f"Check Maven Central for the raw POM if needed:\n"
            f"https://repo1.maven.org/maven2/{pom.group_id.replace('.', '/')}/{pom.artifact_id}/{pom.version}/{pom.artifact_id}-{pom.version}.pom"
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        if candidate.value.startswith("relocated:"):
            parts = candidate.value.split(":")
            if len(parts) >= 3:
                spec.pom_data.group_id = parts[1]
                spec.pom_data.artifact_id = parts[2]
