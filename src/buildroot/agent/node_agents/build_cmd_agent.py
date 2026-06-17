"""Node 9 — Build Command Agent: build tool detection, flag validation."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a build command reviewer for the buildroot reconstruction pipeline.

Your job: detect the correct build tool and validate the build command. 3 of 31 \
benchmark packages fail because the wrong build tool is used (Maven vs Gradle).

Key checks:
1. **Build tool detection** — check the repo for build.gradle, gradlew, settings.gradle \
(Gradle) vs pom.xml, mvnw (Maven). If Gradle files exist, the build command MUST use Gradle.
2. **Wrapper detection** — prefer ./mvnw or ./gradlew over system mvn/gradle
3. **Flag validation** — verify build flags are correct for the detected plugins
4. **Multi-module build** — for multi-module projects, check if -pl flag is needed

Use Bash to check the repo for build files:
```bash
# Check for Gradle
curl -s https://api.github.com/repos/OWNER/REPO/contents/ | grep -i 'gradle\\|gradlew'
# Check for Maven wrapper
curl -s https://api.github.com/repos/OWNER/REPO/contents/ | grep -i 'mvnw'
```

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "build_command". Each candidate's value should be the \
complete build command (e.g., "./gradlew build -x test" or "mvn clean install -B -DskipTests").
"""


class BuildCmdAgent(NodeAgent):
    node_name = "build_cmd_agent"
    field_name = "build_command"
    system_prompt = SYSTEM_PROMPT

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        pom = spec.pom_data
        repo_parts = spec.source_repo.rstrip("/").split("/")
        owner = repo_parts[-2] if len(repo_parts) >= 2 else ""
        repo = repo_parts[-1] if len(repo_parts) >= 1 else ""

        subdir = pom.properties.get("_buildroot_subdir", "")

        plugins = [p.get("artifactId", "") for p in pom.build_plugins[:10]]

        return (
            f"Detect the correct build tool and validate the build command.\n\n"
            f"Artifact: {pom.group_id}:{pom.artifact_id}:{pom.version}\n"
            f"Source repo: {spec.source_repo}\n"
            f"Current build commands: {spec.build_commands}\n"
            f"Maven version: {spec.maven_version}\n"
            f"Modules: {pom.modules}\n"
            f"Build plugins: {plugins}\n"
            f"Subdirectory (if multi-module): {subdir}\n\n"
            f"Check the repo for build system files:\n"
            f"curl -s 'https://api.github.com/repos/{owner}/{repo}/contents/' | "
            f"python3 -c \"import sys,json; files=[f['name'] for f in json.load(sys.stdin)]; "
            f"print([f for f in files if any(k in f.lower() for k in ['gradle','maven','mvn','pom','build'])])\"\n\n"
            f"If Gradle files exist (build.gradle, gradlew), the command should be:\n"
            f"  ./gradlew build -x test  (if gradlew exists)\n"
            f"  gradle build -x test     (fallback)\n\n"
            f"If Maven with wrapper:\n"
            f"  ./mvnw clean install -B -DskipTests\n\n"
            f"Consider -pl flag for multi-module projects."
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        if candidate.value and candidate.value.strip():
            spec.build_commands = [candidate.value.strip()]
