"""Node 7 — Image Agent: Docker Hub registry API tag verification."""

from __future__ import annotations

from typing import Any

from buildroot.agent.node_agents.base import NodeAgent
from buildroot.pipeline.models import BuildrootSpec

SYSTEM_PROMPT = """\
You are a container base image reviewer for the buildroot reconstruction pipeline.

Your job: verify that the resolved container base image tag actually exists on Docker Hub, \
and find alternatives if it doesn't. 6 of 31 benchmark packages fail because the base \
image tag doesn't exist.

Key checks:
1. **Tag existence** — verify the tag via Docker Hub registry v2 API
2. **Alternative tags** — if the tag doesn't exist, find the closest match
3. **Tag format** — ensure correct format (e.g., eclipse-temurin needs -jdk suffix)

Docker Hub tag verification steps:
```bash
# Get auth token
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/IMAGE_NAME:pull" | jq -r .token)
# Check tag exists (200=yes, 404=no)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  "https://registry-1.docker.io/v2/library/IMAGE_NAME/manifests/TAG"
# List available tags
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://registry-1.docker.io/v2/library/IMAGE_NAME/tags/list"
```

For eclipse-temurin images:
- `eclipse-temurin:21-jdk` — standard tag
- `eclipse-temurin:21-jdk-jammy` — Ubuntu 22.04
- `eclipse-temurin:21-jdk-noble` — Ubuntu 24.04

Return your findings as ranked candidates with evidence types from the hierarchy:
direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default

The field_updated should be "base_image". Each candidate's value should be the full \
image:tag string (e.g., "eclipse-temurin:17-jdk").
"""


class ImageAgent(NodeAgent):
    node_name = "image_agent"
    field_name = "base_image"
    system_prompt = SYSTEM_PROMPT

    def should_activate(self, gap_report, spec_overrides=None) -> bool:
        return True

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        jdk = spec.jdk_spec
        image_name = jdk.base_image.split(":")[0] if ":" in jdk.base_image else jdk.base_image
        tag = jdk.base_image.split(":")[1] if ":" in jdk.base_image else ""

        if "/" not in image_name:
            registry_name = f"library/{image_name}"
        else:
            registry_name = image_name

        return (
            f"Verify the container base image tag exists on Docker Hub.\n\n"
            f"Artifact: {spec.pom_data.group_id}:{spec.pom_data.artifact_id}:{spec.pom_data.version}\n"
            f"JDK version: {jdk.version}\n"
            f"JDK distribution: {jdk.distribution}\n"
            f"Current base image: {jdk.base_image}\n\n"
            f"Verify this tag exists:\n"
            f"1. Get token: TOKEN=$(curl -s 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:{registry_name}:pull' | jq -r .token)\n"
            f"2. Check tag: curl -s -o /dev/null -w '%{{http_code}}' -H \"Authorization: Bearer $TOKEN\" "
            f"-H 'Accept: application/vnd.docker.distribution.manifest.v2+json' "
            f"'https://registry-1.docker.io/v2/{registry_name}/manifests/{tag}'\n\n"
            f"If the tag doesn't exist (404), find alternatives by listing tags:\n"
            f"curl -s -H \"Authorization: Bearer $TOKEN\" "
            f"'https://registry-1.docker.io/v2/{registry_name}/tags/list' | jq '.tags | map(select(contains(\"{jdk.version}\")))[:20]'\n\n"
            f"Common eclipse-temurin patterns:\n"
            f"- {jdk.version}-jdk (standard)\n"
            f"- {jdk.version}-jdk-jammy (Ubuntu 22.04)\n"
            f"- {jdk.version}-jdk-noble (Ubuntu 24.04)"
        )

    def _apply_candidate(self, spec: BuildrootSpec, candidate) -> None:
        if candidate.value and ":" in candidate.value:
            spec.jdk_spec.base_image = candidate.value.strip()
