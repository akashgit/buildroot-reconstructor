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
    "3.0.5": "d98d766be9254222920c1d541efd466ae6502b82a39166c90d65ffd7ea357dd9",
    "3.2.3": "bf3f04aadee3a67158aebdfb0b4cb022063329d459d10fd6b4b02223e10aa8ed",
    "3.2.5": "8c190264bdf591ff9f1268dc0ad940a2726f9e958e367716a09b8aaa7e74a755",
    "3.3.1": "153564900617218a126f78d2603d060d0a15f19f3ec1689fc2b7692a3c15b9aa",
    "3.3.3": "3a8dc4a12ab9f3607a1a2097bbab0150c947ad6719d8f1bb6d5b47d0fb0c4779",
    "3.3.9": "6e3e9c949ab4695a204f74038717aa7b2689b1be94875899ac1b3fe42800ff82",
    "3.5.0": "beb91419245395bd69a4a6edad5ca3ec1a8b64e41457672dc687c173a495f034",
    "3.5.2": "707b1f6e390a65bde4af4cdaf2a24d45fc19a6ded00fff02e91626e3e42ceaff",
    "3.5.3": "b52956373fab1dd4277926507ab189fb797b3bc51a2a267a193c931fffad8408",
    "3.5.4": "ce50b1c91364cb77efe3776f756a6d92b76d9038b0a0782f7d53acf1e997a14d",
    "3.6.0": "6a1b346af36a1f1a491c1c1a141667c5de69b42e6611d3687df26868bc0f4637",
    "3.6.1": "2528c35a99c30f8940cc599ba15d34359d58bec57af58c1075519b8cd33b69e7",
    "3.6.2": "3fbc92d1961482d6fbd57fbf3dd6d27a4de70778528ee3fb44aa7d27eb32dfdc",
    "3.6.3": "26ad91d751b3a9a53087aefa743f4e16a17741d3915b219cf74112bf87a438c5",
    "3.8.1": "b98a1905eb554d07427b2e5509ff09bd53e2f1dd7a0afa38384968b113abef02",
    "3.8.2": "8dae10b09feb7b8e4c079fc39a11f3296ab630fd9bc44ecea0fb288cec7770f7",
    "3.8.3": "0f1597d11085b8fe93d84652a18c6deea71ece9fabba45a02cf6600c7758fd5b",
    "3.8.4": "2cdc9c519427bb20fdc25bef5a9063b790e4abd930e7b14b4e9f4863d6f9f13c",
    "3.8.5": "88e30700f32a3f60e0d28d0f12a3525d29b7c20c72d130153df5b5d6d890c673",
    "3.8.6": "c7047a48deb626abf26f71ab3643d296db9b1e67f1faa7d988637deac876b5a9",
    "3.8.7": "628b49352130d1d25d5519b1c724f0efe58b86bad55f37a694ca8f73f11e3604",
    "3.8.8": "17811e108701af5985bf5167abbd47c06e92c6c6bd1c13a1a1c095c9b4ecc32a",
    "3.9.0": "b118e624ec6f7abd8fc49e6cb23f134dbbab1119d88718fc09d798d33756dd72",
    "3.9.1": "0869a4f71238e3eeec21051d062cfd915d34abe905c9bfebf94cd34578db0be7",
    "3.9.2": "809ef3220c6d179195c06c324cb9a6d34d8ecba566c5cfd8eb83167bc034117d",
    "3.9.3": "e1e13ac0c42f3b64d900c57ffc652ecef682b8255d7d354efbbb4f62519da4f1",
    "3.9.4": "ff66b70c830a38d331d44f6c25a37b582471def9a161c93902bac7bea3098319",
    "3.9.5": "5fd272b105041fe81e2e42f6399765e015fc4938ef3753ba4af9f0119d84ef7c",
    "3.9.6": "6eedd2cae3626d6ad3a5c9ee324bd265853d64297f07f033430755bd0e0c3a4b",
    "3.9.7": "c8fb9f620e5814588c2241142bbd9827a08e3cb415f7aa437f2ed44a3eeab62c",
    "3.9.8": "067672629075b740e3d0a928e21021dd615a53287af36d4ccca44e87e081d102",
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
