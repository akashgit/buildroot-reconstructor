"""Configurable trusted source registry for JDK and base image provenance."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse

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


DEFAULT_TRUSTED_DOMAINS = frozenset({
    "archive.apache.org",
    "downloads.apache.org",
    "dlcdn.apache.org",
    "repo1.maven.org",
    "repo.maven.apache.org",
    "maven-central.storage-download.googleapis.com",
    "plugins.gradle.org",
    "services.gradle.org",
    "github.com",
    "raw.githubusercontent.com",
    "adoptium.net",
    "download.java.net",
})

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


MAVEN_CHECKSUMS: dict[str, str] = {
    "3.6.3": "26ad91d751b3a9a53087aefa743f4e16a17741d3915b219cf74112bf87a438c5",
    "3.8.8": "17811e108701af5985bf5167abbd47c06e92c6c6bd1c13a1a1c095c9b4ecc32a",
    "3.9.6": "6eedd2cae3626d6ad3a5c9ee324bd265853d64297f07f033430755bd0e0c3a4b",
    "3.9.9": "7a9cdf674fc1703d6382f5f330b3d110ea1b512b51f1652846d9e4e8a588d766",
}


class TrustedSourceRegistry:
    """Registry of trusted JDK sources with version resolution."""

    _DIGEST_TTL = 86400  # 24 hours

    def __init__(self, config: dict | None = None) -> None:
        self._sources: list[TrustedSource] = []
        self._default_provider: str = "adoptium"
        self._trusted_domains: frozenset[str] = DEFAULT_TRUSTED_DOMAINS
        self._digest_cache: dict[str, tuple[str, float]] = {}

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

    def is_trusted_image(
        self, image_ref: str, max_tier: SourceTier = SourceTier.TIER_1,
    ) -> tuple[bool, TrustedSource | None]:
        """Check if an image reference matches a trusted source."""
        normalized = self._normalize_image_ref(image_ref)
        for source in self._tier_sorted_sources():
            if source.tier.value > max_tier.value:
                continue
            if not source.image_pattern:
                continue
            pattern = re.escape(source.image_pattern).replace(r"\{version\}", r"[\w.-]+")
            if re.fullmatch(pattern, normalized):
                return True, source
        return False, None

    def is_trusted_download_url(self, url: str) -> bool:
        """Check if a download URL comes from a trusted domain."""
        try:
            parsed = urlparse(url)
            domain = parsed.hostname or ""
        except Exception:
            return False
        return domain in self._trusted_domains

    def resolve_image_digest(self, image_ref: str) -> str | None:
        """Query the registry for the current manifest digest via skopeo."""
        now = time.time()
        cached = self._digest_cache.get(image_ref)
        if cached and (now - cached[1]) < self._DIGEST_TTL:
            return cached[0]

        if not shutil.which("skopeo"):
            logger.debug("skopeo not available, skipping digest resolution")
            return None

        try:
            proc = subprocess.run(
                ["skopeo", "inspect", "--raw", f"docker://{image_ref}"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                logger.debug("skopeo inspect failed for %s: %s", image_ref, proc.stderr)
                return None

            raw_bytes = proc.stdout.encode("utf-8")
            digest = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"

            self._digest_cache[image_ref] = (digest, now)
            return digest
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("Digest resolution failed for %s: %s", image_ref, e)
            return None

    def get_maven_checksum(self, version: str) -> str | None:
        """Return SHA-256 checksum for a Maven binary distribution."""
        return MAVEN_CHECKSUMS.get(version)

    @staticmethod
    def _normalize_image_ref(image_ref: str) -> str:
        """Normalize Docker image references for matching."""
        ref = image_ref
        if "@sha256:" in ref:
            ref = ref.split("@sha256:")[0]
        ref = ref.replace("index.docker.io", "docker.io")
        if "/" not in ref.split(":")[0]:
            ref = f"docker.io/library/{ref}"
        if ref.startswith("docker.io/library/"):
            ref = "docker.io/" + ref[len("docker.io/library/"):]
        return ref

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
        sources_cfg: dict = config.get("sources", {})
        sources: list[TrustedSource] = []

        provider_defaults: dict[str, dict] = {
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

        for provider, cfg_raw in sources_cfg.items():
            cfg: dict = cfg_raw if isinstance(cfg_raw, dict) else {}
            defaults: dict = provider_defaults.get(provider, {})
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
