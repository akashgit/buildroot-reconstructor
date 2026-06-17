"""Node 6 — JDK Agent: cross-reference POM compiler settings, CI matrix, .java-version."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a JDK version reviewer for the buildroot reconstruction pipeline.

Your job: validate and improve the resolved JDK version by cross-referencing multiple sources:
1. **POM compiler settings** — maven.compiler.source, maven.compiler.target, \
maven.compiler.release, jdk.version properties
2. **CI matrix** — JDK version from GitHub Actions java-version, CI env vars
3. **.java-version file** — some projects have a .java-version file in the repo root
4. **JAR manifest** — Build-Jdk-Spec from the published JAR on Maven Central
5. **Toolchains** — Maven toolchains.xml if present

Cross-reference all available sources and flag conflicts. The correct JDK version \
should be the one that was ACTUALLY used to build the published artifact.

You have access to Read, Bash, and WebSearch tools. Use Bash to:
- curl the GitHub API to check for .java-version
- Fetch the JAR manifest from Maven Central
- Check POM properties for compiler settings

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "jdk_version". Each candidate's value should be the JDK \
major version number (e.g., "17", "21", "11", "8").
"""


class JdkAgent(NodeAgent):
    node_name = "jdk_agent"
    field_name = "jdk_version"
    system_prompt = SYSTEM_PROMPT

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        jdk = spec.jdk_spec
        pom = spec.pom_data

        compiler_props = {}
        for key in ["maven.compiler.source", "maven.compiler.target",
                     "maven.compiler.release", "jdk.version", "java.version"]:
            if key in pom.properties:
                compiler_props[key] = pom.properties[key]

        ci_java = ""
        if spec.ci_data and spec.ci_data.java_version:
            ci_java = spec.ci_data.java_version.value

        repo_parts = spec.source_repo.rstrip("/").split("/")
        owner = repo_parts[-2] if len(repo_parts) >= 2 else ""
        repo = repo_parts[-1] if len(repo_parts) >= 1 else ""

        group_path = pom.group_id.replace(".", "/")
        jar_url = f"https://repo1.maven.org/maven2/{group_path}/{pom.artifact_id}/{pom.version}/{pom.artifact_id}-{pom.version}.jar"

        return (
            f"Cross-reference JDK version for this Maven artifact.\n\n"
            f"Artifact: {pom.group_id}:{pom.artifact_id}:{pom.version}\n"
            f"Source repo: {spec.source_repo}\n\n"
            f"Current JDK spec:\n"
            f"  Version: {jdk.version}\n"
            f"  Distribution: {jdk.distribution}\n"
            f"  Base image: {jdk.base_image}\n"
            f"  Source: {jdk.source_description}\n"
            f"  Confidence: {jdk.confidence.level.value if jdk.confidence else 'unknown'}\n"
            f"  Conflicts: {jdk.conflicts}\n\n"
            f"POM compiler properties: {compiler_props}\n"
            f"CI java-version: {ci_java}\n\n"
            f"Check these sources:\n"
            f"1. .java-version file: curl -s https://api.github.com/repos/{owner}/{repo}/contents/.java-version\n"
            f"2. JAR manifest: curl -s {jar_url} | python3 -c \"import sys,zipfile,io; z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())); print(z.read('META-INF/MANIFEST.MF').decode())\"\n"
            f"3. POM properties already extracted above"
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        version = candidate.value.strip()
        if version and version.isdigit():
            spec.jdk_spec.version = version
