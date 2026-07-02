"""Configurable trusted source registry for JDK and base image provenance."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

DEFAULT_LTS_VERSIONS = [8, 11, 17, 21, 25]


class SourceTier(Enum):
    """Trust tier for asset sources."""

    TIER_1 = 1  # SLSA L3 — Adoptium, Red Hat UBI
    TIER_2 = 2  # Signed — Corretto, Docker Official
    TIER_3 = 3  # Archive/unverified — jdk.java.net, AdoptOpenJDK legacy


class JdkResolutionStrategy(Enum):
    """Strategy for resolving JDK versions against trusted sources."""

    NEAREST_LTS_ABOVE = "nearest_lts_above"
    BUILD_FROM_SOURCE = "build_from_source"
    EXACT_ONLY = "exact_only"


@dataclass
class TrustedSource:
    """A trusted provider of JDK binaries or container images."""

    provider: str
    registry: str
    tier: SourceTier
    verification: list[str] = field(default_factory=list)
    slsa_level: int | None = None
    jdk_versions: list[str] = field(default_factory=list)
    image_pattern: str = ""


@dataclass
class TrustedJdkResolution:
    """Result of resolving a JDK version against trusted sources."""

    resolved_version: str
    requested_version: str
    resolution_type: str  # "exact" | "substituted" | "build_from_source" | "unavailable"
    source: TrustedSource | None
    base_image: str
    provenance: dict = field(default_factory=dict)
    substitution_reason: str | None = None


DEFAULT_SOURCES = [
    TrustedSource(
        provider="adoptium",
        registry="docker.io",
        tier=SourceTier.TIER_1,
        verification=["gpg", "checksum", "sbom"],
        slsa_level=3,
        jdk_versions=["8", "11", "17", "21", "25"],
        image_pattern="docker.io/eclipse-temurin:{version}-jdk",
    ),
    TrustedSource(
        provider="redhat_ubi",
        registry="registry.access.redhat.com",
        tier=SourceTier.TIER_1,
        verification=["rpm_signature"],
        slsa_level=None,
        jdk_versions=["11", "17", "21", "25"],
        image_pattern="registry.access.redhat.com/ubi9/openjdk-{version}",
    ),
    TrustedSource(
        provider="corretto",
        registry="docker.io",
        tier=SourceTier.TIER_2,
        verification=["gpg", "checksum"],
        slsa_level=None,
        jdk_versions=["8", "11", "17", "21"],
        image_pattern="docker.io/amazoncorretto:{version}",
    ),
    TrustedSource(
        provider="jdk_archive",
        registry="jdk.java.net",
        tier=SourceTier.TIER_3,
        verification=[],
        slsa_level=None,
        jdk_versions=["9", "10", "12", "13", "14", "15", "16"],
        image_pattern="",
    ),
]


class TrustedSourceRegistry:
    """Registry of trusted JDK sources with version resolution."""

    def __init__(self, config: dict | None = None) -> None:
        self._sources: list[TrustedSource] = []
        self._default_provider: str = "adoptium"

        if config:
            self._default_provider = config.get("default_tier1_provider", "adoptium")
            self._sources = self._build_sources_from_config(config)
        else:
            self._sources = list(DEFAULT_SOURCES)

    def resolve_trusted_jdk(
        self,
        version: str,
        strategy: JdkResolutionStrategy = JdkResolutionStrategy.NEAREST_LTS_ABOVE,
    ) -> TrustedJdkResolution:
        major = self._extract_major(version)

        tier1_sources = [
            s for s in self._tier_sorted_sources()
            if s.tier == SourceTier.TIER_1
        ]
        for source in tier1_sources:
            if major in source.jdk_versions:
                base_image = self._resolve_image(source, major)
                logger.info(
                    "Resolved JDK %s to %s from %s (exact match, Tier %d)",
                    version, major, source.provider, source.tier.value,
                )
                return TrustedJdkResolution(
                    resolved_version=major,
                    requested_version=version,
                    resolution_type="exact",
                    source=source,
                    base_image=base_image,
                    provenance=self.get_provenance(source),
                )

        if strategy == JdkResolutionStrategy.BUILD_FROM_SOURCE:
            logger.info(
                "JDK %s not in trusted sources; resolution type: build_from_source",
                version,
            )
            return TrustedJdkResolution(
                resolved_version=major,
                requested_version=version,
                resolution_type="build_from_source",
                source=None,
                base_image="",
                provenance={},
                substitution_reason=(
                    f"JDK {major} not available from trusted sources; "
                    "build from verified OpenJDK source"
                ),
            )

        if strategy == JdkResolutionStrategy.NEAREST_LTS_ABOVE:
            major_int = int(major)
            for lts in DEFAULT_LTS_VERSIONS:
                if lts >= major_int:
                    lts_str = str(lts)
                    for source in self._tier_sorted_sources():
                        if lts_str in source.jdk_versions:
                            base_image = self._resolve_image(source, lts_str)
                            reason = (
                                f"JDK {major} not in trusted sources; "
                                f"substituted with nearest LTS above: JDK {lts_str}"
                            )
                            logger.info(
                                "Resolved JDK %s → %s from %s (substituted, Tier %d)",
                                version, lts_str, source.provider, source.tier.value,
                            )
                            return TrustedJdkResolution(
                                resolved_version=lts_str,
                                requested_version=version,
                                resolution_type="substituted",
                                source=source,
                                base_image=base_image,
                                provenance=self.get_provenance(source),
                                substitution_reason=reason,
                            )

        logger.warning("JDK %s: no trusted resolution available", version)
        return TrustedJdkResolution(
            resolved_version=major,
            requested_version=version,
            resolution_type="unavailable",
            source=None,
            base_image="",
            provenance={},
            substitution_reason=f"JDK {major} not available from any trusted source",
        )

    def resolve_trusted_base_image(
        self, jdk_version: str, provider: str | None = None
    ) -> str | None:
        major = self._extract_major(jdk_version)
        for source in self._tier_sorted_sources():
            if provider and source.provider != provider:
                continue
            if major in source.jdk_versions and source.image_pattern:
                return self._resolve_image(source, major)
        return None

    def get_provenance(self, source: TrustedSource) -> dict:
        return {
            "provider": source.provider,
            "tier": source.tier.value,
            "verification": list(source.verification),
            "slsa_level": source.slsa_level,
            "registry": source.registry,
        }

    def _tier_sorted_sources(self) -> list[TrustedSource]:
        preferred = [s for s in self._sources if s.provider == self._default_provider]
        others = [s for s in self._sources if s.provider != self._default_provider]
        all_sources = preferred + others
        return sorted(all_sources, key=lambda s: s.tier.value)

    def _resolve_image(self, source: TrustedSource, version: str) -> str:
        if source.provider == "redhat_ubi":
            ubi_base = "ubi8" if version == "11" else "ubi9"
            return f"registry.access.redhat.com/{ubi_base}/openjdk-{version}"
        if source.image_pattern:
            return source.image_pattern.format(version=version)
        return ""

    @staticmethod
    def _extract_major(version: str) -> str:
        if version.startswith("1.") and len(version) >= 3:
            return version[2:]
        return version.split(".")[0] if "." in version else version

    @staticmethod
    def _build_sources_from_config(config: dict) -> list[TrustedSource]:
        sources_cfg = config.get("sources", {})
        sources: list[TrustedSource] = []

        provider_defaults = {
            "adoptium": {
                "registry": "docker.io",
                "verification": ["gpg", "checksum", "sbom"],
                "slsa_level": 3,
                "image_pattern": "docker.io/eclipse-temurin:{version}-jdk",
            },
            "redhat_ubi": {
                "registry": "registry.access.redhat.com",
                "verification": ["rpm_signature"],
                "slsa_level": None,
                "image_pattern": "registry.access.redhat.com/ubi9/openjdk-{version}",
            },
            "corretto": {
                "registry": "docker.io",
                "verification": ["gpg", "checksum"],
                "slsa_level": None,
                "image_pattern": "docker.io/amazoncorretto:{version}",
            },
            "jdk_archive": {
                "registry": "jdk.java.net",
                "verification": [],
                "slsa_level": None,
                "image_pattern": "",
            },
        }

        for provider, cfg in sources_cfg.items():
            defaults = provider_defaults.get(provider, {})
            tier_val = cfg.get("tier", 3)
            sources.append(TrustedSource(
                provider=provider,
                registry=cfg.get("registry", defaults.get("registry", "")),
                tier=SourceTier(tier_val),
                verification=cfg.get("verification", defaults.get("verification", [])),
                slsa_level=cfg.get("slsa_level", defaults.get("slsa_level")),
                jdk_versions=cfg.get("jdk_versions", []),
                image_pattern=cfg.get(
                    "image_pattern", defaults.get("image_pattern", "")
                ),
            ))

        return sources
