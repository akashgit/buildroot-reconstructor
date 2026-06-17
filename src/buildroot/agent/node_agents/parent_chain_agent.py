"""Node 2 — Parent Chain Agent: missing parents, BOM import validation."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a Maven parent chain reviewer for the buildroot reconstruction pipeline.

Your job: validate the resolved parent POM chain for completeness and correctness:
1. **Missing parents** — check if any parent in the chain could not be resolved
2. **BOM import validation** — check if <dependencyManagement> imports reference valid BOMs
3. **Property inheritance** — verify that key properties are inherited correctly

You have access to Read, Bash, and WebSearch tools. Use them to:
- Fetch parent POMs from Maven Central to verify they exist
- Check BOM import coordinates

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "parent_chain". Each candidate's value should describe the \
finding (e.g., "missing_parent:org.apache:apache:33" or "valid" if chain is complete).
"""


class ParentChainAgent(NodeAgent):
    node_name = "parent_chain_agent"
    field_name = "parent_chain"
    system_prompt = SYSTEM_PROMPT

    def should_activate(self, gap_report, spec_overrides=None) -> bool:
        return True

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        pom = spec.pom_data
        chain_info = []
        for p in pom.parent_chain:
            chain_info.append(f"  {p.get('groupId', '?')}:{p.get('artifactId', '?')}:{p.get('version', '?')}")
        chain_str = "\n".join(chain_info) if chain_info else "  (empty)"

        dep_mgmt = []
        for d in pom.dependency_management[:10]:
            dep_mgmt.append(f"  {d.get('groupId', '?')}:{d.get('artifactId', '?')}:{d.get('version', '?')} scope={d.get('scope', '')}")
        dep_mgmt_str = "\n".join(dep_mgmt) if dep_mgmt else "  (none)"

        return (
            f"Review the parent chain and BOM imports for this Maven artifact.\n\n"
            f"Artifact: {pom.group_id}:{pom.artifact_id}:{pom.version}\n\n"
            f"Parent chain:\n{chain_str}\n\n"
            f"Dependency management (BOM imports):\n{dep_mgmt_str}\n\n"
            f"Verify each parent POM exists on Maven Central and check BOM imports."
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        pass
