"""Supply chain audit log — trace every external asset in a build."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

logger = __import__("logging").getLogger(__name__)

_APT_INSTALL_RE = re.compile(
    r"(?:apt-get|apt)\s+install\s+(?:-\S+\s+)*(.+?)(?:\s*&&|\s*\\|\s*$)",
    re.IGNORECASE,
)

_YUM_INSTALL_RE = re.compile(
    r"(?:yum|dnf|microdnf)\s+install\s+(?:-\S+\s+)*(.+?)(?:\s*&&|\s*\\|\s*$)",
    re.IGNORECASE,
)

_GIT_CLONE_RE = re.compile(
    r"git\s+clone\s+(?:(?:--depth\s+(\d+)|--branch\s+(\S+)|-b\s+(\S+)|\S+)\s+)*"
    r"(https?://\S+|git://\S+|git@\S+)",
    re.IGNORECASE,
)

_CURL_WGET_RE = re.compile(
    r"(?:curl\s+.*?|wget\s+.*?)(https?://\S+)",
    re.IGNORECASE,
)

_ADD_URL_RE = re.compile(
    r"^ADD\s+(https?://\S+)",
    re.IGNORECASE | re.MULTILINE,
)

_MAVEN_DOWNLOAD_RE = re.compile(
    r"Downloading\s+(?:from\s+\S+:\s+)?(https?://\S+)",
)

_GRADLE_DOWNLOAD_RE = re.compile(
    r"Download\s+(https?://\S+)",
)


@dataclass
class AuditEntry:
    """A single external asset consumed during the build."""

    type: str
    name: str
    source: str
    version: str | None = None
    tag: str | None = None
    digest: str | None = None
    url: str | None = None
    ref: str | None = None
    depth: int | None = None
    framework: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"type": self.type, "name": self.name, "source": self.source}
        for k in ("version", "tag", "digest", "url", "ref", "depth", "framework"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d


@dataclass
class AuditLog:
    """Collection of audit entries with computed properties."""

    assets: list[AuditEntry] = field(default_factory=list)

    @property
    def total_assets(self) -> int:
        return len(self.assets)

    @property
    def unique_sources(self) -> list[str]:
        return sorted({a.source for a in self.assets if a.source})

    def to_dict(self) -> dict:
        return {
            "total_assets": self.total_assets,
            "unique_sources": self.unique_sources,
            "assets": [a.to_dict() for a in self.assets],
        }


def extract_static_assets(containerfile: str) -> list[AuditEntry]:
    """Parse a Containerfile for statically declared external assets."""
    entries: list[AuditEntry] = []

    for line in containerfile.splitlines():
        stripped = line.strip()

        if stripped.upper().startswith("FROM "):
            _parse_from(stripped, entries)
            continue

    for line in containerfile.splitlines():
        stripped = line.strip()

        if stripped.upper().startswith("ADD "):
            m = _ADD_URL_RE.match(stripped)
            if m:
                url = m.group(1)
                entries.append(AuditEntry(
                    type="direct_download",
                    name=url.rsplit("/", 1)[-1],
                    source=_url_host(url),
                    url=url,
                ))

    for m in _APT_INSTALL_RE.finditer(containerfile):
        packages = _split_package_list(m.group(1))
        for pkg in packages:
            entries.append(AuditEntry(type="os_package", name=pkg, source="apt"))

    for m in _YUM_INSTALL_RE.finditer(containerfile):
        packages = _split_package_list(m.group(1))
        for pkg in packages:
            entries.append(AuditEntry(type="os_package", name=pkg, source="yum"))

    for m in _GIT_CLONE_RE.finditer(containerfile):
        url = m.group(4)
        depth_str = m.group(1)
        ref = m.group(2) or m.group(3)
        repo_name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        entry = AuditEntry(
            type="git_repo",
            name=repo_name,
            source=_url_host(url),
            url=url,
        )
        if depth_str:
            entry.depth = int(depth_str)
        if ref:
            entry.ref = ref
        entries.append(entry)

    for m in _CURL_WGET_RE.finditer(containerfile):
        url = m.group(1)
        if any(e.url == url for e in entries):
            continue
        entries.append(AuditEntry(
            type="direct_download",
            name=url.rsplit("/", 1)[-1],
            source=_url_host(url),
            url=url,
        ))

    return entries


def extract_dynamic_assets(build_log: str) -> list[AuditEntry]:
    """Parse a build log for dynamically downloaded dependencies."""
    entries: list[AuditEntry] = []
    seen_urls: set[str] = set()

    for m in _MAVEN_DOWNLOAD_RE.finditer(build_log):
        url = m.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        name, version, entry_type = _parse_maven_url(url)
        entries.append(AuditEntry(
            type=entry_type,
            name=name,
            source=_url_host(url),
            url=url,
            version=version,
            framework="maven",
        ))

    for m in _GRADLE_DOWNLOAD_RE.finditer(build_log):
        url = m.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        name, version, entry_type = _parse_maven_url(url)
        entries.append(AuditEntry(
            type=entry_type,
            name=name,
            source=_url_host(url),
            url=url,
            version=version,
            framework="gradle",
        ))

    return entries


def build_audit_log(
    static: list[AuditEntry],
    dynamic: list[AuditEntry],
    reference_jar_url: str | None = None,
) -> AuditLog:
    """Merge static and dynamic audit entries, deduplicate, optionally add reference JAR."""
    seen: set[tuple[str, str, str]] = set()
    merged: list[AuditEntry] = []

    for entry in static + dynamic:
        key = (entry.type, entry.name, entry.source)
        if key not in seen:
            seen.add(key)
            merged.append(entry)

    if reference_jar_url:
        merged.append(AuditEntry(
            type="reference_jar",
            name=reference_jar_url.rsplit("/", 1)[-1],
            source=_url_host(reference_jar_url),
            url=reference_jar_url,
        ))

    return AuditLog(assets=merged)


def _parse_from(line: str, entries: list[AuditEntry]) -> None:
    """Parse a FROM instruction into an AuditEntry."""
    parts = line.split()
    if len(parts) < 2:
        return
    image = parts[1]
    if image.lower() == "scratch":
        return
    tag = None
    digest = None
    name = image
    if "@sha256:" in image:
        name, digest = image.split("@", 1)
    elif ":" in image and not image.startswith("localhost"):
        parts_img = image.rsplit(":", 1)
        if len(parts_img) == 2 and "/" not in parts_img[1]:
            name = parts_img[0]
            tag = parts_img[1]

    source = "docker.io"
    if "/" in name:
        first_part = name.split("/")[0]
        if "." in first_part or ":" in first_part:
            source = first_part

    entries.append(AuditEntry(
        type="base_image",
        name=name,
        source=source,
        tag=tag,
        digest=digest,
    ))


def _split_package_list(raw: str) -> list[str]:
    """Split an apt/yum package list, filtering out flags and continuations."""
    packages: list[str] = []
    for token in raw.split():
        token = token.strip().rstrip("\\")
        if not token or token.startswith("-") or token.startswith("#"):
            continue
        if "=" in token:
            packages.append(token.split("=")[0])
        else:
            packages.append(token)
    return packages


def _url_host(url: str) -> str:
    """Extract hostname from a URL."""
    url = url.split("://", 1)[-1] if "://" in url else url
    return url.split("/")[0].split(":")[0]


def _parse_maven_url(url: str) -> tuple[str, str | None, str]:
    """Extract artifact name, version, and type from a Maven/Gradle repository URL."""
    path = url.split("://", 1)[-1] if "://" in url else url
    parts = path.split("/")

    entry_type = "build_dependency"
    if "maven-plugin" in url or "-plugin-" in url:
        entry_type = "build_plugin"

    filename = parts[-1] if parts else url
    name = filename
    version: str | None = None

    m = re.match(r"^(.+?)-(\d[\w.\-]*?)\.(?:jar|pom|xml|module)$", filename)
    if m:
        name = m.group(1)
        version = m.group(2)

    return name, version, entry_type
