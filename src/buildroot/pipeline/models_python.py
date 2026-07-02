"""Python-specific data models for the buildroot reconstruction pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from buildroot.pipeline.models import CIData, Confidence, GapReport


@dataclass
class PyProjectData:
    """Parsed Python project metadata from pyproject.toml / setup.cfg / setup.py."""

    name: str = ""
    version: str = ""
    requires_python: str = ""
    build_backend: str = ""
    build_requires: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: dict[str, list[str]] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)
    entry_points: dict[str, dict[str, str]] = field(default_factory=dict)
    classifiers: list[str] = field(default_factory=list)
    project_urls: dict[str, str] = field(default_factory=dict)
    has_c_extensions: bool = False
    package_dir: str = ""


@dataclass
class PythonSpec:
    """Resolved Python version specification."""

    version: str = ""
    base_image: str = ""
    needs_build_tools: bool = False
    confidence: Confidence | None = None
    source_description: str = ""
    conflicts: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PyBuildrootSpec:
    """Complete reconstructed Python build environment specification."""

    pyproject_data: PyProjectData = field(default_factory=PyProjectData)
    ci_data: CIData | None = None
    python_spec: PythonSpec = field(default_factory=PythonSpec)
    source_repo: str = ""
    git_tag: str = ""
    build_backend: str = ""
    build_command: str = ""
    system_packages: list[str] = field(default_factory=list)
    pre_build_commands: list[str] = field(default_factory=list)
    post_build_commands: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    pip_extra_index: str = ""
    template_id: str = ""
    gaps: GapReport = field(default_factory=GapReport)
