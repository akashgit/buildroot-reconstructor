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

_GITBOX_RE = re.compile(
    r"gitbox\.apache\.org/repos/asf/([^/.]+?)(?:\.git)?(?:/|$)"
)


def _normalize_scm_url(raw: str) -> str:
    url = raw.strip()
    for prefix in ("scm:git:", "scm:svn:", "scm:"):
        if url.lower().startswith(prefix):
            url = url[len(prefix):]
            break
    if url.startswith("git://"):
        url = "https://" + url[6:]
    if url.startswith("git@"):
        url = url[4:]
        url = "https://" + url.replace(":", "/", 1)
    return url


def discover_repo_from_pom(pom_data) -> tuple[str, str] | None:
    """Try to discover a GitHub repo owner/name from POM SCM or groupId."""
    from buildroot.pipeline.models import PomData

    if not isinstance(pom_data, PomData):
        return None

    scm_urls: list[str] = []

    for key in ("connection", "developerConnection", "url"):
        val = pom_data.scm.get(key, "")
        if val:
            scm_urls.append(val)

    for plugin in pom_data.build_plugins:
        if plugin.get("artifactId") == "maven-scm-plugin":
            config = plugin.get("configuration", {})
            if "connectionUrl" in config:
                scm_urls.append(config["connectionUrl"])

    url_prop = pom_data.properties.get("project.scm.url", "")
    if url_prop:
        scm_urls.append(url_prop)

    if pom_data.url:
        scm_urls.append(pom_data.url)

    for raw_url in scm_urls:
        normalized = _normalize_scm_url(raw_url)

        match = _parse_github_url(normalized)
        if match:
            return match

        m = _GITBOX_RE.search(normalized)
        if m:
            repo_name = m.group(1)
            return ("apache", repo_name)

        m = _GITBOX_RE.search(raw_url)
        if m:
            repo_name = m.group(1)
            return ("apache", repo_name)

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


def _generate_date_tag_candidates(version: str) -> list[str]:
    """Generate zero-padded tag candidates for date-based versions.

    For a version like ``2021.10.8`` (year.month.day), the actual git
    tag is often ``2021.10.08`` (zero-padded day/month).  This helper
    detects the pattern and returns the padded variants.
    """
    parts = version.split(".")
    if len(parts) < 3:
        return []
    # First part must look like a year (4 digits starting with 19 or 20)
    if not re.match(r"^(19|20)\d{2}$", parts[0]):
        return []

    padded_parts = [parts[0]]
    changed = False
    for p in parts[1:]:
        if len(p) == 1 and p.isdigit():
            padded_parts.append(p.zfill(2))
            changed = True
        else:
            padded_parts.append(p)

    if not changed:
        return []

    padded_version = ".".join(padded_parts)
    return [padded_version, f"v{padded_version}"]


def discover_git_tag(
    repo_owner: str,
    repo_name: str,
    artifact_id: str,
    version: str,
) -> str:
    """Discover the correct git tag for a version by querying GitHub API.

    Tries patterns: v{version}, {artifactId}-{version},
    rel/{artifactId}-{version}, bare {version}, plus zero-padded date
    variants for date-based versions.  Falls back to v{version}.
    """
    candidates = [
        f"v{version}",
        f"{artifact_id}-{version}",
        f"rel/{artifact_id}-{version}",
        version,
    ]
    # Add zero-padded candidates for date-based versions (e.g. 2021.10.8 -> 2021.10.08)
    candidates.extend(_generate_date_tag_candidates(version))

    url = f"{GITHUB_API}/repos/{repo_owner}/{repo_name}/tags?per_page=100"
    resp = _get(url)
    if resp is None:
        return f"v{version}"

    tags = resp.json()
    if not isinstance(tags, list):
        return f"v{version}"
    all_pages_tags: list[str] = [t.get("name", "") for t in tags]

    # If version not likely in first page, try a few more pages
    if all_pages_tags and not any(version in t for t in all_pages_tags):
        link_header = resp.headers.get("Link", "")
        page = 2
        while "next" in link_header and page <= 5:
            next_url = f"{GITHUB_API}/repos/{repo_owner}/{repo_name}/tags?per_page=100&page={page}"
            next_resp = _get(next_url)
            if next_resp is None:
                break
            next_tags = next_resp.json()
            if not isinstance(next_tags, list) or not next_tags:
                break
            all_pages_tags.extend(t.get("name", "") for t in next_tags)
            if any(version in t for t in [t.get("name", "") for t in next_tags]):
                break
            link_header = next_resp.headers.get("Link", "")
            page += 1

    tag_set = set(all_pages_tags)

    for candidate in candidates:
        if candidate in tag_set:
            logger.info("Matched git tag: %s", candidate)
            return candidate

    for tag_name in all_pages_tags:
        if tag_name.endswith(version):
            logger.info("Fuzzy-matched git tag: %s", tag_name)
            return tag_name

    return f"v{version}"


def fetch_maven_wrapper_properties(
    repo_owner: str, repo_name: str
) -> str | None:
    """Fetch .mvn/wrapper/maven-wrapper.properties from a GitHub repo."""
    return fetch_file_content(
        repo_owner, repo_name, ".mvn/wrapper/maven-wrapper.properties"
    )


def _parse_github_url(url: str) -> tuple[str, str] | None:
    for pattern in _GITHUB_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return (m.group(1), m.group(2))
    return None
