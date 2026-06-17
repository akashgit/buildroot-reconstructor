"""Node 8 — Tag Agent: git tag verification, naming convention detection."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a git tag reviewer for the buildroot reconstruction pipeline.

Your job: verify the discovered git tag exists and find the correct one if it doesn't. \
2 of 31 benchmark packages fail because the git tag is wrong.

Key checks:
1. **Tag verification** — use `git ls-remote --tags --refs` to verify the tag exists
2. **Naming conventions** — try multiple patterns: v{version}, {artifactId}-{version}, \
rel/{artifactId}-{version}, {version}, release-{version}
3. **Monorepo tags** — some projects use different tag patterns for sub-modules

Use Bash to run git ls-remote directly:
```bash
git ls-remote --tags --refs REPO_URL "refs/tags/v*VERSION*"
git ls-remote --tags --refs REPO_URL "refs/tags/*VERSION*"
git ls-remote --tags --refs REPO_URL | grep VERSION
```

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "git_tag". Each candidate's value should be the tag name \
(e.g., "v3.14.0" or "commons-lang3-3.14.0").
"""


class TagAgent(NodeAgent):
    node_name = "tag_agent"
    field_name = "git_tag"
    system_prompt = SYSTEM_PROMPT

    def should_activate(self, gap_report) -> bool:
        return True

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        pom = spec.pom_data
        return (
            f"Verify the git tag for this Maven artifact.\n\n"
            f"Artifact: {pom.group_id}:{pom.artifact_id}:{pom.version}\n"
            f"Source repo: {spec.source_repo}\n"
            f"Current git tag: {spec.git_tag}\n\n"
            f"Verify the tag exists:\n"
            f"git ls-remote --tags --refs {spec.source_repo} 'refs/tags/{spec.git_tag}'\n\n"
            f"If not found, try these patterns:\n"
            f"git ls-remote --tags --refs {spec.source_repo} | grep -i '{pom.version}'\n\n"
            f"Common tag patterns to try:\n"
            f"- v{pom.version}\n"
            f"- {pom.artifact_id}-{pom.version}\n"
            f"- rel/{pom.artifact_id}-{pom.version}\n"
            f"- {pom.version}\n"
            f"- release-{pom.version}\n"
            f"- {pom.group_id.split('.')[-1]}-{pom.version}"
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        if candidate.value and candidate.value.strip():
            spec.git_tag = candidate.value.strip()
