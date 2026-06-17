"""Node 5 — CI Agent: correct workflow selection, alternative CI systems."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a CI/CD configuration reviewer for the buildroot reconstruction pipeline.

Your job: validate the CI configuration and find the correct build workflow:
1. **Correct workflow selection** — if multiple CI workflows exist, identify the one \
that builds the project (not just tests, linting, or docs)
2. **Alternative CI systems** — check for Jenkins (Jenkinsfile), Makefile, BUILDING.md, \
or other build systems if no GitHub Actions found
3. **Build command extraction** — extract the actual build command from the CI config

You have access to Read, Bash, and WebSearch tools. Use Bash to:
- curl the GitHub API to list workflow files
- curl https://api.github.com/repos/{owner}/{repo}/contents/.github/workflows
- Look for Jenkinsfile, Makefile, build.sh, BUILDING.md

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "ci_data". Each candidate's value should be the build command \
extracted from CI (e.g., "mvn clean install -B -DskipTests").
"""


class CIAgent(NodeAgent):
    node_name = "ci_agent"
    field_name = "build_command"
    system_prompt = SYSTEM_PROMPT

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        ci_info = "No CI data found"
        if spec.ci_data:
            ci_info = (
                f"CI type: {spec.ci_data.ci_type}\n"
                f"Build commands found: {spec.ci_data.build_commands}\n"
                f"Runner OS: {spec.ci_data.runner_os}\n"
                f"Env vars: {spec.ci_data.env_vars}"
            )

        repo_parts = spec.source_repo.rstrip("/").split("/")
        owner = repo_parts[-2] if len(repo_parts) >= 2 else ""
        repo = repo_parts[-1] if len(repo_parts) >= 1 else ""

        return (
            f"Review CI configuration for this Maven artifact.\n\n"
            f"Artifact: {spec.pom_data.group_id}:{spec.pom_data.artifact_id}:{spec.pom_data.version}\n"
            f"Source repo: {spec.source_repo}\n\n"
            f"Current CI data:\n{ci_info}\n\n"
            f"Current build commands: {spec.build_commands}\n\n"
            f"If the repo is on GitHub, check workflows:\n"
            f"curl -s https://api.github.com/repos/{owner}/{repo}/contents/.github/workflows\n\n"
            f"Also check for alternative build systems:\n"
            f"curl -s https://api.github.com/repos/{owner}/{repo}/contents/ | grep -i 'jenkinsfile\\|makefile\\|build.sh\\|BUILDING'"
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        if candidate.value and candidate.value.strip():
            spec.build_commands = [candidate.value.strip()]
