"""Container image resolution — locate and parse Dockerfiles/Containerfiles."""

from __future__ import annotations

import logging
import re
import shutil
import tempfile

import requests
from dockerfile_parse import DockerfileParser

from buildroot.pipeline.models import Source
from buildroot.utils import github_api

logger = logging.getLogger(__name__)

APT_GET_RE = re.compile(
    r"apt-get\s+install\s+(?:-[a-zA-Z]+\s+)*(.+?)(?:\s*&&|\s*;|\s*$)",
    re.MULTILINE,
)
YUM_INSTALL_RE = re.compile(
    r"yum\s+install\s+(?:-[a-zA-Z]+\s+)*(.+?)(?:\s*&&|\s*;|\s*$)",
    re.MULTILINE,
)
DOCKER_HUB_API = "https://hub.docker.com/v2/repositories"


class ContainerImageResolver:
    """Resolve container image references to extract build environment details."""

    def resolve(
        self,
        image_ref: str,
        repo_owner: str | None = None,
    ) -> dict:
        """Resolve a container image reference to environment details.

        Tries GitHub Dockerfile search first, then Docker Hub metadata.
        """
        parts = image_ref.split(":")
        image_name = parts[0]
        namespace, name = self._split_image_ref(image_name)

        dockerfile_content = self._search_github_dockerfile(
            namespace, name, repo_owner
        )
        if dockerfile_content:
            result = self.parse_dockerfile(dockerfile_content)
            result["source"] = Source.OBSERVED.value
            result["image_ref"] = image_ref
            return result

        hub_result = self._query_docker_hub(namespace, name)
        if hub_result:
            hub_result["source"] = Source.INFERRED.value
            hub_result["image_ref"] = image_ref
            return hub_result

        return {
            "base_image": image_ref,
            "installed_packages": [],
            "java_home": "",
            "env_vars": {},
            "source": Source.INFERRED.value,
            "image_ref": image_ref,
        }

    def parse_dockerfile(self, content: str) -> dict:
        """Parse a Dockerfile/Containerfile to extract environment details."""
        tmp = tempfile.mkdtemp(prefix="buildroot-df-")
        parser = DockerfileParser(path=tmp)
        parser.content = content

        base_image = self._extract_base_image(parser)
        packages = self._extract_packages(parser)
        java_home, env_vars = self._extract_env(parser)

        shutil.rmtree(tmp, ignore_errors=True)

        return {
            "base_image": base_image,
            "installed_packages": packages,
            "java_home": java_home,
            "env_vars": env_vars,
        }

    def _extract_base_image(self, parser: DockerfileParser) -> str:
        """Extract the base image — for multi-stage builds, take the last FROM."""
        from_instructions = []
        for instruction in parser.structure:
            if instruction["instruction"] == "FROM":
                from_instructions.append(instruction["value"])

        if not from_instructions:
            return ""

        last_from = from_instructions[-1]
        parts = last_from.split()
        return parts[0] if parts else last_from

    def _extract_packages(self, parser: DockerfileParser) -> list[str]:
        """Extract installed packages from RUN commands."""
        packages = []
        for instruction in parser.structure:
            if instruction["instruction"] != "RUN":
                continue
            value = instruction["value"]
            for pattern in (APT_GET_RE, YUM_INSTALL_RE):
                for match in pattern.finditer(value):
                    raw = match.group(1)
                    for pkg in raw.split():
                        cleaned = pkg.strip().rstrip("\\")
                        if cleaned and not cleaned.startswith("-"):
                            packages.append(cleaned)
        return packages

    def _extract_env(
        self, parser: DockerfileParser
    ) -> tuple[str, dict[str, str]]:
        """Extract ENV instructions, returning (java_home, all_env_vars)."""
        env_vars: dict[str, str] = {}
        java_home = ""
        for instruction in parser.structure:
            if instruction["instruction"] != "ENV":
                continue
            value = instruction["value"]
            pairs = self._parse_env_value(value)
            for k, v in pairs.items():
                env_vars[k] = v
                if k == "JAVA_HOME":
                    java_home = v
        return java_home, env_vars

    def _parse_env_value(self, value: str) -> dict[str, str]:
        """Parse ENV instruction value into key-value pairs.

        Handles both:
          ENV KEY=VALUE
          ENV KEY VALUE
        """
        result: dict[str, str] = {}
        if "=" in value:
            for part in re.findall(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)', value):
                key, val = part
                val = val.strip('"')
                result[key] = val
        else:
            parts = value.split(None, 1)
            if len(parts) == 2:
                result[parts[0]] = parts[1]
            elif len(parts) == 1:
                result[parts[0]] = ""
        return result

    def _split_image_ref(self, image_name: str) -> tuple[str, str]:
        """Split an image reference into (namespace, name)."""
        if "/" in image_name:
            parts = image_name.split("/", 1)
            return parts[0], parts[1]
        return "library", image_name

    def _search_github_dockerfile(
        self,
        namespace: str,
        name: str,
        repo_owner: str | None,
    ) -> str | None:
        """Search GitHub for a Dockerfile matching the image."""
        owner = repo_owner or namespace
        for dockerfile_name in ("Dockerfile", "Containerfile"):
            content = github_api.fetch_file_content(owner, name, dockerfile_name)
            if content:
                logger.info(
                    "Found %s for %s/%s on GitHub", dockerfile_name, owner, name
                )
                return content
        return None

    def _query_docker_hub(self, namespace: str, name: str) -> dict | None:
        """Query Docker Hub API for image metadata."""
        url = f"{DOCKER_HUB_API}/{namespace}/{name}/"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return {
                "base_image": f"{namespace}/{name}",
                "installed_packages": [],
                "java_home": "",
                "env_vars": {},
                "description": data.get("description", ""),
                "full_description": data.get("full_description", ""),
            }
        except (requests.RequestException, ValueError):
            logger.warning("Failed to query Docker Hub for %s/%s", namespace, name)
            return None
