"""GitHub REST API client for workflow and file fetching."""

from __future__ import annotations

import base64
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _get(url: str, *, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        resp = requests.get(url, headers=_headers(), timeout=30)
        if resp.status_code == 200:
            return resp
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            wait = 2 ** attempt
            logger.warning(
                "GitHub API rate limit (403) on %s — retrying in %ds. "
                "Set GITHUB_TOKEN for higher limits.",
                url, wait,
            )
            time.sleep(wait)
            continue
        resp.raise_for_status()
    return None


def fetch_file_content(repo_owner: str, repo_name: str, path: str) -> str | None:
    """Fetch a file from a GitHub repo via the REST API.

    Returns decoded file content, or None if the file doesn't exist.
    """
    url = f"{GITHUB_API}/repos/{repo_owner}/{repo_name}/contents/{path}"
    resp = _get(url)
    if resp is None:
        return None
    data = resp.json()
    if isinstance(data, list):
        return None
    encoding = data.get("encoding", "")
    content = data.get("content", "")
    if encoding == "base64" and content:
        return base64.b64decode(content).decode("utf-8")
    return content


def list_directory(repo_owner: str, repo_name: str, path: str) -> list[dict] | None:
    """List files in a directory of a GitHub repo.

    Returns list of file metadata dicts, or None if directory doesn't exist.
    """
    url = f"{GITHUB_API}/repos/{repo_owner}/{repo_name}/contents/{path}"
    resp = _get(url)
    if resp is None:
        return None
    data = resp.json()
    if isinstance(data, list):
        return data
    return None


_GITHUB_URL_PATTERNS = [
    re.compile(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?(?:/|$)"),
]


def discover_repo_from_pom(pom_data) -> tuple[str, str] | None:
    """Try to discover a GitHub repo owner/name from POM SCM or groupId."""
    from buildroot.pipeline.models import PomData

    if not isinstance(pom_data, PomData):
        return None

    scm_urls: list[str] = []
    for prop_key in ("scm.url", "scm.connection", "scm.developerConnection"):
        parts = prop_key.split(".")
        if len(parts) == 2 and parts[0] == "scm":
            pass
    for plugin in pom_data.build_plugins:
        if plugin.get("artifactId") == "maven-scm-plugin":
            config = plugin.get("configuration", {})
            if "connectionUrl" in config:
                scm_urls.append(config["connectionUrl"])

    url_prop = pom_data.properties.get("project.scm.url", "")
    if url_prop:
        scm_urls.append(url_prop)

    for url in scm_urls:
        match = _parse_github_url(url)
        if match:
            return match

    group_id = pom_data.group_id
    if group_id.startswith("org.springframework"):
        artifact = pom_data.artifact_id
        if "spring-boot" in artifact:
            return ("spring-projects", "spring-boot")
        if "spring-security" in artifact:
            return ("spring-projects", "spring-security")
        if "spring-cloud" in artifact:
            return ("spring-cloud", artifact)
        return ("spring-projects", "spring-framework")

    return None


def _parse_github_url(url: str) -> tuple[str, str] | None:
    for pattern in _GITHUB_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return (m.group(1), m.group(2))
    return None
