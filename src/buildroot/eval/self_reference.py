"""Self-built reference JAR production from source repositories."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

_SCM_PREFIX_RE = re.compile(r"^scm:(git|svn|hg):")
_GIT_SUFFIX_RE = re.compile(r"\.git$")
_GITHUB_SSH_RE = re.compile(
    r"(?:ssh://)?git@github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.\s]+)"
)
_GITHUB_HTTPS_RE = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/.\s]+)"
)
_GITBOX_RE = re.compile(
    r"https?://gitbox\.apache\.org/repos/asf\?p=(?P<project>[^.]+)\.git"
)

_MAVEN_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def _normalize_scm_url(raw: str) -> tuple[str, str] | None:
    raw = _SCM_PREFIX_RE.sub("", raw).strip()

    m = _GITBOX_RE.match(raw)
    if m:
        return ("apache", m.group("project"))

    raw = _GIT_SUFFIX_RE.sub("", raw).strip()

    m = _GITHUB_SSH_RE.search(raw)
    if m:
        return (m.group("owner"), m.group("repo"))

    m = _GITHUB_HTTPS_RE.search(raw)
    if m:
        return (m.group("owner"), m.group("repo"))

    return None


def _parse_scm_from_pom(pom_path: Path) -> tuple[str, str] | None:
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
    except (ET.ParseError, OSError):
        return None

    ns = _MAVEN_NS
    scm = root.find("m:scm", ns)
    if scm is None:
        scm = root.find("scm")

    if scm is not None:
        for tag_name in ["url", "connection", "developerConnection"]:
            el = scm.find(f"m:{tag_name}", ns)
            if el is None:
                el = scm.find(tag_name)
            if el is not None and el.text:
                result = _normalize_scm_url(el.text)
                if result:
                    return result

    url_el = root.find("m:url", ns) or root.find("url")
    if url_el is not None and url_el.text:
        result = _normalize_scm_url(url_el.text)
        if result:
            return result

    return None


def _query_deps_dev(group_id: str, artifact_id: str, version: str) -> tuple[str, str] | None:
    url = f"https://api.deps.dev/v3/systems/maven/packages/{group_id}%3A{artifact_id}/versions/{version}"
    try:
        proc = subprocess.run(
            ["curl", "-sf", url],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout)
        for link in data.get("links", []):
            if link.get("label") in ("SOURCE_REPO", "HOMEPAGE"):
                result = _normalize_scm_url(link.get("url", ""))
                if result:
                    return result
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, KeyError):
        pass
    return None


def _search_github(artifact_id: str) -> tuple[str, str] | None:
    try:
        proc = subprocess.run(
            ["gh", "search", "repos", artifact_id, "--language", "java",
             "--limit", "5", "--json", "owner,name"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return None
        results = json.loads(proc.stdout)
        if results:
            best = results[0]
            return (best["owner"]["login"], best["name"])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, KeyError):
        pass
    return None


def discover_source_repo(
    group_id: str, artifact_id: str, version: str,
    pom_path: Path | None = None,
) -> tuple[str, str] | None:
    """Discover the source repository for a Maven artifact.

    Returns (owner, repo) tuple or None.
    Fallback chain: POM SCM → POM <url> → deps.dev API → GitHub search.
    """
    if pom_path and pom_path.exists():
        result = _parse_scm_from_pom(pom_path)
        if result:
            return result

    result = _query_deps_dev(group_id, artifact_id, version)
    if result:
        return result

    result = _search_github(artifact_id)
    if result:
        return result

    return None


def resolve_tag(
    owner: str, repo: str, artifact_id: str, version: str,
) -> str | None:
    """Find the release tag matching the version.

    Tries patterns: v{version}, {artifactId}-{version},
    rel/{artifactId}-{version}, bare {version}, then fuzzy substring.
    Prefers shorter tags on multiple matches.
    """
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/tags", "--paginate",
             "--jq", ".[].name"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return None
        tags = [t.strip() for t in proc.stdout.strip().splitlines() if t.strip()]
    except (subprocess.TimeoutExpired, OSError):
        return None

    if not tags:
        return None

    exact_patterns = [
        f"v{version}",
        f"{artifact_id}-{version}",
        f"rel/{artifact_id}-{version}",
        version,
    ]
    for pattern in exact_patterns:
        if pattern in tags:
            return pattern

    candidates = [t for t in tags if version in t]
    if candidates:
        candidates.sort(key=len)
        return candidates[0]

    return None


def build_from_source(
    owner: str, repo: str, tag: str,
    artifact_id: str, version: str,
    jdk_version: str, tmpdir: Path,
) -> Path | None:
    """Clone at tag and build, returning path to built JAR or None."""
    source_dir = tmpdir / "self_built_source"
    repo_url = f"https://github.com/{owner}/{repo}.git"

    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", tag, repo_url, str(source_dir)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            logger.warning("git clone failed for %s/%s@%s: %s", owner, repo, tag, proc.stderr[:200])
            return None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("git clone error: %s", e)
        return None

    pom_path = source_dir / "pom.xml"
    if pom_path.exists():
        try:
            pom_text = pom_path.read_text()
            if "SNAPSHOT" in pom_text and f"<version>{version}</version>" not in pom_text:
                logger.info("Skipping build: SNAPSHOT dependencies detected")
                return None
        except OSError:
            pass

    build_system = _detect_build_system(source_dir)
    if build_system == "maven":
        build_cmd = [
            "mvn", "package", "-DskipTests", "-B", "-q",
            "-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z",
        ]
    elif build_system == "gradle":
        build_cmd = ["gradle", "build", "-x", "test", "-q"]
    else:
        logger.warning("Unknown build system in %s/%s", owner, repo)
        return None

    try:
        proc = subprocess.run(
            build_cmd,
            capture_output=True, text=True, timeout=600,
            cwd=str(source_dir),
        )
        if proc.returncode != 0:
            logger.warning("Build failed for %s/%s: %s", owner, repo, proc.stderr[-500:])
            return None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Build error: %s", e)
        return None

    return _find_built_jar(source_dir, artifact_id, version)


def _detect_build_system(source_dir: Path) -> str:
    if (source_dir / "pom.xml").exists():
        return "maven"
    if (source_dir / "build.gradle").exists() or (source_dir / "build.gradle.kts").exists():
        return "gradle"
    return "unknown"


def _find_built_jar(source_dir: Path, artifact_id: str, version: str) -> Path | None:
    search_dirs = ["target", "build/libs"]
    for subdir in source_dir.iterdir():
        if subdir.is_dir():
            search_dirs.append(str(subdir / "target"))
            search_dirs.append(str(subdir / "build" / "libs"))

    for search_dir in search_dirs:
        search_path = Path(search_dir) if Path(search_dir).is_absolute() else source_dir / search_dir
        if not search_path.exists():
            continue
        for jar in search_path.glob("*.jar"):
            if jar.name.endswith("-sources.jar") or jar.name.endswith("-javadoc.jar"):
                continue
            if jar.name.startswith("original-"):
                continue
            if artifact_id in jar.name and version in jar.name:
                return jar

    for search_dir in search_dirs:
        search_path = Path(search_dir) if Path(search_dir).is_absolute() else source_dir / search_dir
        if not search_path.exists():
            continue
        for jar in search_path.glob("*.jar"):
            if jar.name.endswith("-sources.jar") or jar.name.endswith("-javadoc.jar"):
                continue
            if jar.name.startswith("original-"):
                continue
            if jar.stat().st_size > 1024:
                return jar

    return None


def build_reference_jar(
    group_id: str, artifact_id: str, version: str,
    jdk_version: str, tmpdir: Path,
) -> Path | None:
    """Orchestrate: discover source → resolve tag → build from source.

    Returns path to self-built reference JAR or None on any failure.
    """
    repo_info = discover_source_repo(group_id, artifact_id, version)
    if not repo_info:
        logger.info("Source repo not found for %s:%s:%s", group_id, artifact_id, version)
        return None

    owner, repo = repo_info
    tag = resolve_tag(owner, repo, artifact_id, version)
    if not tag:
        logger.info("No matching tag found for %s/%s version %s", owner, repo, version)
        return None

    jar = build_from_source(owner, repo, tag, artifact_id, version, jdk_version, tmpdir)
    if not jar:
        logger.info("Build failed for %s/%s@%s", owner, repo, tag)
        return None

    logger.info("Self-built reference JAR: %s", jar)
    return jar
