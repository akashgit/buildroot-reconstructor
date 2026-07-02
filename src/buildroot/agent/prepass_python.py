"""Deterministic pre-pass for Python packages — fast data gathering before the Analysis Agent."""

from __future__ import annotations

import re
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from buildroot.agent.prepass import PrePassFinding
from buildroot.parsers.pyproject import PyProjectParser
from buildroot.pipeline.models_python import PyProjectData
from buildroot.resolvers.python_version import PythonVersionResolver
from buildroot.utils import pypi_client
from buildroot.utils.github_api import (
    _generate_date_tag_candidates,
    discover_git_tag,
)

logger = structlog.get_logger()

_GITHUB_URL_RE = re.compile(
    r"(?:https?://|git\+https?://|git://|git@)"
    r"github\.com[:/]([^/]+)/([^/.#?]+?)(?:\.git)?(?:[/#?]|$)"
)

_REPO_URL_KEYS = [
    "Source",
    "Source Code",
    "Repository",
    "GitHub",
    "Code",
    "Homepage",
]


@dataclass
class PyPrePassFindings:
    """All findings from the Python pre-pass."""

    source_repo: PrePassFinding | None = None
    git_tag: PrePassFinding | None = None
    python_version: PrePassFinding | None = None
    build_backend: PrePassFinding | None = None
    build_command: PrePassFinding | None = None
    base_image: PrePassFinding | None = None

    pyproject_data: PyProjectData = field(default_factory=PyProjectData)
    ci_data: dict | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    attempted_but_failed: list[str] = field(default_factory=list)

    sdist_path: Path | None = None
    sdist_entry_count: int | None = None
    pkg_info: dict[str, str] = field(default_factory=dict)

    def to_prompt(self) -> str:
        """Format findings for the Analysis Agent prompt."""
        sections: list[str] = []
        sections.append("## Pre-Pass Findings (Python)\n")

        # Package coordinate
        if self.pyproject_data.name or self.pyproject_data.version:
            sections.append(
                f"- **package**: `{self.pyproject_data.name}=={self.pyproject_data.version}`"
            )

        finding_fields: list[tuple[str, PrePassFinding | None]] = [
            ("build_backend", self.build_backend),
            ("build_command", self.build_command),
            ("python_version", self.python_version),
            ("base_image", self.base_image),
            ("source_repo", self.source_repo),
            ("git_tag", self.git_tag),
        ]

        for name, finding in finding_fields:
            if finding is not None:
                sections.append(
                    f"- **{name}**: `{finding.value}` "
                    f"(source={finding.source}, confidence={finding.confidence})\n"
                    f"  Evidence: {finding.evidence}"
                )

        if self.pyproject_data.dependencies:
            sections.append("\n### Dependencies")
            for dep in self.pyproject_data.dependencies[:20]:
                sections.append(f"- {dep}")
            if len(self.pyproject_data.dependencies) > 20:
                sections.append(
                    f"- ... and {len(self.pyproject_data.dependencies) - 20} more"
                )

        if self.env_vars:
            sections.append("\n### Environment Variables")
            for k, v in self.env_vars.items():
                sections.append(f"- {k}={v}")

        if self.pkg_info:
            sections.append("\n### PKG-INFO")
            for k, v in self.pkg_info.items():
                sections.append(f"- {k}: {v[:200]}")

        if self.sdist_entry_count is not None:
            sections.append(f"\n### Artifact\n- sdist entry count: {self.sdist_entry_count}")

        if self.sdist_path:
            sections.append(f"- sdist: {self.sdist_path}")

        if self.attempted_but_failed:
            sections.append("\n### Attempted But Failed")
            for item in self.attempted_but_failed:
                sections.append(f"- {item}")

        return "\n".join(sections)

    def to_dict(self) -> dict:
        """Serializable representation."""
        result: dict[str, Any] = {}
        for name in (
            "source_repo",
            "git_tag",
            "python_version",
            "build_backend",
            "build_command",
            "base_image",
        ):
            finding = getattr(self, name)
            if finding is not None:
                result[name] = {
                    "value": finding.value,
                    "source": finding.source,
                    "confidence": finding.confidence,
                    "evidence": finding.evidence,
                }
        if self.env_vars:
            result["env_vars"] = self.env_vars
        if self.pkg_info:
            result["pkg_info"] = self.pkg_info
        if self.sdist_entry_count is not None:
            result["sdist_entry_count"] = self.sdist_entry_count
        if self.attempted_but_failed:
            result["attempted_but_failed"] = self.attempted_but_failed
        if self.pyproject_data.name:
            result["pyproject_data"] = {
                "name": self.pyproject_data.name,
                "version": self.pyproject_data.version,
                "build_backend": self.pyproject_data.build_backend,
                "requires_python": self.pyproject_data.requires_python,
                "dependencies": self.pyproject_data.dependencies,
            }
        return result


def parse_python_coordinate(coordinate: str) -> tuple[str, str]:
    """Parse 'package==version' into (package, version).

    Also accepts 'package=version' and 'package:version'.
    Raises ValueError if unparseable.
    """
    # Try separators in order; == must be checked before =
    coord = coordinate.strip()
    for sep in ("==", "=", ":"):
        idx = coord.find(sep)
        if idx >= 0:
            pkg = coord[:idx].strip()
            ver = coord[idx + len(sep):].strip()
            if pkg and ver:
                return pkg, ver
            # Found separator but missing pkg or ver — don't try other seps
            break
    raise ValueError(
        f"Cannot parse Python coordinate: {coordinate!r}. "
        "Expected format: package==version"
    )


def _verify_tag_exists(repo_url: str, tag: str) -> bool:
    """Check if a tag exists using git ls-remote (no API auth needed)."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url, f"refs/tags/{tag}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _discover_python_tag(
    repo_url: str, version: str, package: str
) -> tuple[str, bool]:
    """Discover the correct git tag for a Python package using git ls-remote.

    Returns ``(tag, verified)`` where *verified* is True when the tag was
    confirmed to exist via ``git ls-remote``.  Python packages most commonly
    use bare version tags (e.g. ``1.1.4``), so bare version is tried first.
    """
    # Build candidates in priority order for Python packages
    candidates: list[str] = [version]  # bare version first (most common)
    candidates.append(f"v{version}")
    candidates.append(f"{package}-{version}")

    # Add date-based candidates (e.g. 2021.10.8 -> 2021.10.08)
    for dc in _generate_date_tag_candidates(version):
        if dc not in candidates:
            candidates.append(dc)

    for tag in candidates:
        if _verify_tag_exists(repo_url, tag):
            return tag, True

    # Nothing verified -- return bare version as the best guess for Python
    return candidates[0], False


def run_python_prepass(
    coordinate: str, workspace: Path, *, no_cache: bool = False
) -> PyPrePassFindings:
    """Run the Python pre-pass pipeline.

    Data-gathering only -- no template rendering, no spec decisions.

    Args:
        coordinate: Python package coordinate (e.g. 'requests==2.31.0').
        workspace: Directory for downloaded artefacts.
        no_cache: When True, bypass any local PyPI cache.
    """
    findings = PyPrePassFindings()
    workspace.mkdir(parents=True, exist_ok=True)

    # 1. Parse coordinate
    try:
        package, version = parse_python_coordinate(coordinate)
    except ValueError:
        raise

    # 2. Fetch PyPI JSON metadata
    try:
        metadata = pypi_client.fetch_package_metadata(package, version)
    except Exception as e:
        logger.warning("PyPI metadata fetch failed", error=str(e))
        findings.attempted_but_failed.append(f"PyPI metadata fetch: {e}")
        return findings

    # 3. Extract source repo from PyPI metadata
    try:
        repo_info = _discover_repo_from_pypi(metadata)
        if repo_info:
            owner, repo_name = repo_info
            repo_url = f"https://github.com/{owner}/{repo_name}"
            findings.source_repo = PrePassFinding(
                value=repo_url,
                source="pypi_metadata",
                confidence="high",
                evidence=f"GitHub repo from PyPI project URLs: {owner}/{repo_name}",
            )
        else:
            findings.attempted_but_failed.append(
                "Source repo discovery: no GitHub URL in PyPI metadata"
            )
    except Exception as e:
        logger.warning("Repo discovery failed", error=str(e))
        findings.attempted_but_failed.append(f"Source repo discovery: {e}")

    # 4. Discover git tag
    if findings.source_repo:
        try:
            repo_url = findings.source_repo.value
            parts = repo_url.rstrip("/").split("/")
            owner, repo_name = parts[-2], parts[-1]
            tag = discover_git_tag(owner, repo_name, package, version)

            # If GitHub API returned the default v{version} fallback,
            # it may be wrong for Python packages (bare tags are common).
            # Use git ls-remote to verify/discover the correct tag.
            source = "github_api"
            if tag == f"v{version}":
                py_tag, verified = _discover_python_tag(
                    repo_url, version, package
                )
                if verified:
                    tag = py_tag
                    source = "git_ls_remote"
                else:
                    # ls-remote couldn't verify anything; prefer bare
                    # version for Python over v-prefixed.
                    tag = py_tag

            findings.git_tag = PrePassFinding(
                value=tag,
                source=source,
                confidence="high" if source == "git_ls_remote" else "medium",
                evidence=f"Tag discovery matched: {tag}",
            )
        except Exception as e:
            logger.warning("Git tag discovery failed", error=str(e))
            findings.attempted_but_failed.append(f"Git tag discovery: {e}")

    # 5. Download original sdist
    try:
        sdist_path = workspace / "original.tar.gz"
        pypi_client.download_sdist(
            package, version, sdist_path, metadata=metadata
        )
        findings.sdist_path = sdist_path

        if sdist_path.exists() and tarfile.is_tarfile(sdist_path):
            with tarfile.open(sdist_path, "r:gz") as tf:
                members = tf.getnames()
                findings.sdist_entry_count = len(members)

                # Extract PKG-INFO if present
                for member_name in members:
                    if member_name.endswith("/PKG-INFO") or member_name == "PKG-INFO":
                        try:
                            f = tf.extractfile(member_name)
                            if f:
                                findings.pkg_info = _parse_pkg_info(
                                    f.read().decode("utf-8", errors="replace")
                                )
                        except Exception:
                            pass
                        break
    except Exception as e:
        logger.warning("sdist download failed", error=str(e))
        findings.attempted_but_failed.append(f"sdist download: {e}")

    # 6. Extract and parse pyproject.toml from the sdist
    parser = PyProjectParser()
    pyproject_parsed = None
    setup_cfg_parsed = None
    setup_py_parsed = None

    if findings.sdist_path and findings.sdist_path.exists():
        try:
            pyproject_content = _extract_pyproject_from_sdist(findings.sdist_path)
            if pyproject_content:
                pyproject_parsed = parser.parse_pyproject_toml(pyproject_content)
        except Exception as e:
            logger.warning("pyproject.toml parse failed", error=str(e))
            findings.attempted_but_failed.append(f"pyproject.toml parse: {e}")

        try:
            setup_cfg_content = _extract_setup_cfg_from_sdist(findings.sdist_path)
            if setup_cfg_content:
                setup_cfg_parsed = parser.parse_setup_cfg(setup_cfg_content)
        except Exception as e:
            logger.warning("setup.cfg parse failed", error=str(e))
            findings.attempted_but_failed.append(f"setup.cfg parse: {e}")

        try:
            setup_py_content = _extract_setup_py_from_sdist(findings.sdist_path)
            if setup_py_content:
                setup_py_parsed = parser.parse_setup_py(setup_py_content)
        except Exception as e:
            logger.warning("setup.py parse failed", error=str(e))
            findings.attempted_but_failed.append(f"setup.py parse: {e}")

    # Merge parsed configs (pyproject.toml takes priority)
    merged = parser.merge_configs(pyproject_parsed, setup_cfg_parsed, setup_py_parsed)
    if not merged.name:
        merged.name = package
    if not merged.version:
        merged.version = version
    findings.pyproject_data = merged

    # Also merge in classifiers from PyPI metadata if not present
    pypi_classifiers = pypi_client.extract_classifiers(metadata)
    if pypi_classifiers and not findings.pyproject_data.classifiers:
        findings.pyproject_data.classifiers = pypi_classifiers

    # Merge requires_python from PyPI if missing
    pypi_requires_python = pypi_client.extract_python_requires(metadata)
    if pypi_requires_python and not findings.pyproject_data.requires_python:
        findings.pyproject_data.requires_python = pypi_requires_python

    # 7. Detect build system
    try:
        backend_name = parser.detect_build_system(findings.pyproject_data)
        findings.build_backend = PrePassFinding(
            value=backend_name,
            source="pyproject_toml" if findings.pyproject_data.build_backend else "inferred",
            confidence="high" if findings.pyproject_data.build_backend else "medium",
            evidence=f"Build backend: {findings.pyproject_data.build_backend or 'inferred from build_requires'}",
        )
        cmd = _build_command_for_backend(backend_name)
        findings.build_command = PrePassFinding(
            value=cmd,
            source="inferred",
            confidence="medium",
            evidence=f"Default build command for {backend_name}",
        )
    except Exception as e:
        logger.warning("Build system detection failed", error=str(e))
        findings.attempted_but_failed.append(f"Build system detection: {e}")

    # 8. Resolve Python version
    try:
        resolver = PythonVersionResolver()
        python_spec = resolver.resolve(findings.pyproject_data)
        findings.python_version = PrePassFinding(
            value=python_spec.version,
            source=python_spec.source_description or "resolver",
            confidence="high" if python_spec.confidence and python_spec.confidence.level.value == "observed" else "medium",
            evidence=python_spec.confidence.reason if python_spec.confidence else "Python version resolver",
        )
        findings.base_image = PrePassFinding(
            value=python_spec.base_image,
            source="resolver",
            confidence="medium",
            evidence=f"Base image for Python {python_spec.version}",
        )
    except Exception as e:
        logger.warning("Python version resolution failed", error=str(e))
        findings.attempted_but_failed.append(f"Python version resolution: {e}")

    # 9. Try fetching CI workflows from GitHub for Python version signals
    if findings.source_repo:
        try:
            from buildroot.utils.github_api import fetch_file_content, list_directory

            repo_url = findings.source_repo.value
            parts = repo_url.rstrip("/").split("/")
            owner, repo_name = parts[-2], parts[-1]

            workflow_files = list_directory(owner, repo_name, ".github/workflows")
            if workflow_files:
                for wf_entry in workflow_files[:3]:
                    wf_file = wf_entry["name"] if isinstance(wf_entry, dict) else wf_entry
                    if not str(wf_file).endswith((".yml", ".yaml")):
                        continue
                    content = fetch_file_content(
                        owner, repo_name, f".github/workflows/{wf_file}"
                    )
                    if content:
                        findings.ci_data = {"workflow_file": wf_file, "raw": content[:2000]}
                        break
            else:
                findings.attempted_but_failed.append(
                    "CI workflow fetch: no workflows found"
                )
        except Exception as e:
            logger.warning("CI workflow fetch failed", error=str(e))
            findings.attempted_but_failed.append(f"CI workflow fetch: {e}")

    return findings


def _discover_repo_from_pypi(metadata: dict) -> tuple[str, str] | None:
    """Extract GitHub owner/repo from PyPI metadata.

    Checks project_urls, home_page, and project_url fields.
    """
    info = metadata.get("info", {})
    project_urls = info.get("project_urls") or {}

    # Check project_urls in priority order
    for key in _REPO_URL_KEYS:
        url = project_urls.get(key, "")
        if url:
            match = _parse_github_url(url)
            if match:
                return match

    # Check all project_urls values (catch non-standard key names)
    for url in project_urls.values():
        if url:
            match = _parse_github_url(url)
            if match:
                return match

    # Check home_page
    home_page = info.get("home_page", "")
    if home_page:
        match = _parse_github_url(home_page)
        if match:
            return match

    # Check project_url
    project_url = info.get("project_url", "")
    if project_url:
        match = _parse_github_url(project_url)
        if match:
            return match

    return None


def _parse_github_url(url: str) -> tuple[str, str] | None:
    """Parse a GitHub URL into (owner, repo)."""
    m = _GITHUB_URL_RE.search(url)
    if m:
        return m.group(1), m.group(2)
    return None


def _extract_pyproject_from_sdist(sdist_path: Path) -> str | None:
    """Extract pyproject.toml content from a sdist tarball."""
    return _extract_file_from_sdist(sdist_path, "pyproject.toml")


def _extract_setup_cfg_from_sdist(sdist_path: Path) -> str | None:
    """Extract setup.cfg content from a sdist tarball."""
    return _extract_file_from_sdist(sdist_path, "setup.cfg")


def _extract_setup_py_from_sdist(sdist_path: Path) -> str | None:
    """Extract setup.py content from a sdist tarball."""
    return _extract_file_from_sdist(sdist_path, "setup.py")


def _extract_file_from_sdist(sdist_path: Path, filename: str) -> str | None:
    """Extract a file by name from a sdist tarball.

    Looks for {name}-{version}/{filename} pattern.
    """
    if not sdist_path.exists():
        return None
    try:
        with tarfile.open(sdist_path, "r:gz") as tf:
            for member in tf.getnames():
                # Match {name}-{version}/{filename} or just {filename}
                basename = member.rsplit("/", 1)[-1] if "/" in member else member
                if basename == filename:
                    # Only match top-level files (one directory deep)
                    depth = member.count("/")
                    if depth <= 1:
                        f = tf.extractfile(member)
                        if f:
                            return f.read().decode("utf-8", errors="replace")
    except (tarfile.TarError, OSError):
        return None
    return None


def _build_command_for_backend(backend: str) -> str:
    """Return default build command for a given backend.

    All PEP 517 backends (setuptools, flit, hatch, maturin, scikit-build)
    use ``python -m build --sdist`` which invokes the backend's hooks directly
    — no CLI tool needed.  Only Poetry requires its own CLI because its build
    system is non-standard and the template already installs the poetry CLI.
    """
    if backend == "poetry":
        return "poetry build --format sdist"
    return "python -m build --sdist"


def _parse_pkg_info(content: str) -> dict[str, str]:
    """Parse PKG-INFO content into a dict of key-value pairs."""
    result: dict[str, str] = {}
    current_key: str | None = None
    current_val = ""
    for line in content.splitlines():
        if line.startswith("        ") and current_key is not None:
            # Continuation line in Description
            current_val += "\n" + line.strip()
        elif ": " in line:
            if current_key is not None:
                result[current_key] = current_val
            current_key, current_val = line.split(": ", 1)
            current_key = current_key.strip()
            current_val = current_val.strip()
        elif line.startswith(" ") and current_key is not None:
            current_val += " " + line.strip()
    if current_key is not None:
        result[current_key] = current_val
    # Only keep useful subset
    keep_keys = {
        "Name", "Version", "Summary", "Author", "Author-email",
        "License", "Requires-Python", "Home-page",
    }
    return {k: v for k, v in result.items() if k in keep_keys}
