"""Node 4 — Repo Agent: URL validation, multi-module subdirectory detection."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a source repository reviewer for the buildroot reconstruction pipeline.

Your job: validate and improve the discovered source repository URL. This is the \
highest-impact node agent — 8 of 31 benchmark packages fail due to multi-module issues.

Key checks:
1. **URL validation** — verify the repo URL is accessible and contains the target artifact
2. **Multi-module detection** — if this is a multi-module project, identify the correct \
subdirectory containing the target module's pom.xml
3. **GitHub API search** — if no repo URL was found, search GitHub for the project

For multi-module projects, you MUST:
- Clone or browse the repo to find which subdirectory contains the target artifact
- Check if the root pom.xml has <modules> listing the target
- Return the subdirectory path (e.g., "commons-lang3" for Apache Commons Lang)

You have access to Read, Bash, and WebSearch tools. Use Bash to:
- curl the GitHub API to check repo contents
- curl https://api.github.com/repos/{owner}/{repo}/contents/ to list root files
- curl https://api.github.com/search/repositories?q={artifact}+language:java

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "source_repo". Each candidate's value should be either:
- A repo URL if the current one is wrong (e.g., "https://github.com/apache/commons-lang")
- A repo URL with subdirectory suffix using | separator (e.g., \
"https://github.com/apache/tomcat|java/jakarta/catalina") for multi-module projects
"""


class RepoAgent(NodeAgent):
    node_name = "repo_agent"
    field_name = "source_repo"
    system_prompt = SYSTEM_PROMPT

    def should_activate(self, gap_report, spec_overrides=None) -> bool:
        return True

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        pom = spec.pom_data
        return (
            f"Validate and improve the source repository for this Maven artifact.\n\n"
            f"Artifact: {pom.group_id}:{pom.artifact_id}:{pom.version}\n"
            f"Current repo URL: {spec.source_repo or '(not found)'}\n"
            f"POM SCM: {pom.scm}\n"
            f"POM URL: {pom.url}\n"
            f"Modules declared in POM: {pom.modules}\n"
            f"Packaging: {pom.packaging}\n\n"
            f"Steps:\n"
            f"1. If repo URL exists, verify it's accessible via: "
            f"curl -s -o /dev/null -w '%{{http_code}}' {spec.source_repo or 'N/A'}\n"
            f"2. Check if this is a multi-module project by looking at the root pom.xml\n"
            f"3. If multi-module, find the subdirectory containing {pom.artifact_id}/pom.xml\n"
            f"4. If no repo URL, search GitHub: "
            f"curl -s 'https://api.github.com/search/repositories?q={pom.artifact_id}+language:java&sort=stars'"
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        if "|" in candidate.value:
            repo_url, subdir = candidate.value.split("|", 1)
            spec.source_repo = repo_url.strip()
            if not spec.pom_data.properties.get("_buildroot_subdir"):
                spec.pom_data.properties["_buildroot_subdir"] = subdir.strip()
        elif candidate.value.startswith("https://"):
            spec.source_repo = candidate.value.strip()
