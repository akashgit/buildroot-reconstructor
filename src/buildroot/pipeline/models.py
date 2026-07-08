"""Core data models for the buildroot reconstruction pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Source(Enum):
    """How a value was determined."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    DEFAULTED = "defaulted"


@dataclass
class Annotated:
    """A value with provenance tracking."""

    value: Any
    source: Source
    description: str = ""


@dataclass
class Confidence:
    """Confidence assessment for an inferred value."""

    level: Source
    reason: str


@dataclass
class PomData:
    """Parsed and merged POM data after parent chain resolution."""

    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    packaging: str = "jar"
    parent_chain: list[dict[str, str]] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    dependencies: list[dict[str, str]] = field(default_factory=list)
    build_plugins: list[dict[str, Any]] = field(default_factory=list)
    profiles: list[dict[str, Any]] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    dependency_management: list[dict[str, str]] = field(default_factory=list)
    scm: dict[str, str] = field(default_factory=dict)
    url: str = ""


@dataclass
class CIData:
    """Extracted CI workflow environment data."""

    java_version: Annotated | None = None
    distribution: Annotated | None = None
    build_commands: list[str] = field(default_factory=list)
    system_packages: list[str] = field(default_factory=list)
    container_images: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    runner_os: str = ""
    ci_type: str = ""
    source_annotations: dict[str, Annotated] = field(default_factory=dict)


@dataclass
class JdkSpec:
    """Resolved JDK specification."""

    version: str = ""
    distribution: str = "temurin"
    base_image: str = ""
    confidence: Confidence | None = None
    source_description: str = ""
    conflicts: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DependencyNode:
    """A node in the transitive dependency tree."""

    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    scope: str = "compile"
    children: list[DependencyNode] = field(default_factory=list)


@dataclass
class GapEntry:
    """A single gap in the reconstruction."""

    field: str
    status: str
    reason: str
    source: Source


@dataclass
class GapReport:
    """Aggregate report of gaps and unknowns in the reconstruction."""

    entries: list[GapEntry] = field(default_factory=list)


@dataclass
class BuildrootSpec:
    """Complete reconstructed build environment specification."""

    pom_data: PomData = field(default_factory=PomData)
    ci_data: CIData | None = None
    jdk_spec: JdkSpec = field(default_factory=JdkSpec)
    dependency_tree: DependencyNode | None = None
    maven_version: str = ""
    system_packages: list[str] = field(default_factory=list)
    base_image: str = ""
    build_commands: list[str] = field(default_factory=list)
    source_repo: str = ""
    git_tag: str = ""
    gaps: GapReport = field(default_factory=GapReport)
    extra_build_flags: list[str] = field(default_factory=list)
    reproducibility_env: dict[str, str] = field(default_factory=dict)
    metadata_strip_patterns: list[str] = field(default_factory=list)
    pre_build_commands: list[str] = field(default_factory=list)
    post_build_commands: list[str] = field(default_factory=list)
    config_files: list[dict[str, str]] = field(default_factory=list)
    template_id: str = ""
    build_system: str = ""
    module_path: str | None = None
    artifact_path_pattern: str | None = None
    build_tool_version: str | None = None
    jdk_minor_version: str | None = None
    use_maven_wrapper: bool = False
    provenance_tier: int | None = None
    provenance_provider: str = ""
    provenance_verification: list[str] = field(default_factory=list)
    jdk_resolution_type: str = ""
    jdk_requested_version: str = ""
    trusted_base_image: str = ""
    pnc_builder_image: str = ""
    pnc_build_id: str = ""
    rhel_version: str = ""
