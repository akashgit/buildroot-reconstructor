"""Tests for TrustedSourceRegistry."""

from __future__ import annotations

from buildroot.trust.registry import (
    DEFAULT_LTS_VERSIONS,
    JdkResolutionStrategy,
    SourceTier,
    TrustedSourceRegistry,
)


class TestDefaultInitialization:
    def test_default_sources_include_adoptium_tier1(self):
        reg = TrustedSourceRegistry()
        resolution = reg.resolve_trusted_jdk("17")
        assert resolution.source is not None
        assert resolution.source.provider == "adoptium"
        assert resolution.source.tier == SourceTier.TIER_1

    def test_default_sources_include_ubi_tier1(self):
        reg = TrustedSourceRegistry(config={
            "default_tier1_provider": "redhat_ubi",
            "sources": {
                "redhat_ubi": {"tier": 1, "jdk_versions": ["11", "17", "21", "25"]},
            },
        })
        resolution = reg.resolve_trusted_jdk("17")
        assert resolution.source is not None
        assert resolution.source.provider == "redhat_ubi"
        assert resolution.source.tier == SourceTier.TIER_1

    def test_default_lts_versions(self):
        assert DEFAULT_LTS_VERSIONS == [8, 11, 17, 21, 25]


class TestResolveExact:
    def test_jdk17_exact_match(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk("17")
        assert res.resolution_type == "exact"
        assert res.resolved_version == "17"
        assert res.requested_version == "17"
        assert res.base_image == "docker.io/eclipse-temurin:17-jdk"
        assert res.substitution_reason is None

    def test_jdk8_exact_match(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk("8")
        assert res.resolution_type == "exact"
        assert res.resolved_version == "8"

    def test_jdk21_exact_match(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk("21")
        assert res.resolution_type == "exact"
        assert res.resolved_version == "21"
        assert res.base_image == "docker.io/eclipse-temurin:21-jdk"


class TestResolveSubstituted:
    def test_jdk9_substituted_to_11(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk(
            "9", strategy=JdkResolutionStrategy.NEAREST_LTS_ABOVE
        )
        assert res.resolution_type == "substituted"
        assert res.requested_version == "9"
        assert res.resolved_version == "11"
        assert res.substitution_reason is not None
        assert "nearest LTS" in res.substitution_reason

    def test_jdk10_substituted_to_11(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk(
            "10", strategy=JdkResolutionStrategy.NEAREST_LTS_ABOVE
        )
        assert res.resolution_type == "substituted"
        assert res.resolved_version == "11"

    def test_jdk13_substituted_to_17(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk(
            "13", strategy=JdkResolutionStrategy.NEAREST_LTS_ABOVE
        )
        assert res.resolution_type == "substituted"
        assert res.resolved_version == "17"


class TestResolveBuildFromSource:
    def test_jdk9_build_from_source(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk(
            "9", strategy=JdkResolutionStrategy.BUILD_FROM_SOURCE
        )
        assert res.resolution_type == "build_from_source"
        assert res.requested_version == "9"
        assert res.resolved_version == "9"
        assert res.source is None
        assert res.base_image == ""


class TestResolveExactOnly:
    def test_jdk9_exact_only_unavailable(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk(
            "9", strategy=JdkResolutionStrategy.EXACT_ONLY
        )
        assert res.resolution_type == "unavailable"
        assert res.source is None

    def test_jdk17_exact_only_available(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk(
            "17", strategy=JdkResolutionStrategy.EXACT_ONLY
        )
        assert res.resolution_type == "exact"
        assert res.resolved_version == "17"


class TestResolveBaseImage:
    def test_adoptium_default(self):
        reg = TrustedSourceRegistry()
        image = reg.resolve_trusted_base_image("21")
        assert image == "docker.io/eclipse-temurin:21-jdk"

    def test_ubi_override(self):
        reg = TrustedSourceRegistry(config={
            "default_tier1_provider": "redhat_ubi",
            "sources": {
                "redhat_ubi": {"tier": 1, "jdk_versions": ["11", "17", "21", "25"]},
            },
        })
        image = reg.resolve_trusted_base_image("21")
        assert image == "registry.access.redhat.com/ubi9/openjdk-21"

    def test_ubi_jdk11_uses_ubi8(self):
        reg = TrustedSourceRegistry(config={
            "default_tier1_provider": "redhat_ubi",
            "sources": {
                "redhat_ubi": {"tier": 1, "jdk_versions": ["11", "17", "21", "25"]},
            },
        })
        image = reg.resolve_trusted_base_image("11")
        assert image == "registry.access.redhat.com/ubi8/openjdk-11"

    def test_unknown_version_returns_none(self):
        reg = TrustedSourceRegistry()
        image = reg.resolve_trusted_base_image("99")
        assert image is None


class TestProvenance:
    def test_provenance_metadata_populated(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk("17")
        assert res.provenance["provider"] == "adoptium"
        assert res.provenance["tier"] == 1
        assert "gpg" in res.provenance["verification"]
        assert res.provenance["slsa_level"] == 3

    def test_provenance_empty_for_unavailable(self):
        reg = TrustedSourceRegistry()
        res = reg.resolve_trusted_jdk(
            "9", strategy=JdkResolutionStrategy.EXACT_ONLY
        )
        assert res.provenance == {}


class TestCustomConfig:
    def test_override_tier1_to_ubi(self):
        config = {
            "default_tier1_provider": "redhat_ubi",
            "sources": {
                "redhat_ubi": {"tier": 1, "jdk_versions": ["11", "17", "21", "25"]},
                "adoptium": {"tier": 1, "jdk_versions": ["8", "11", "17", "21", "25"]},
            },
        }
        reg = TrustedSourceRegistry(config=config)
        res = reg.resolve_trusted_jdk("17")
        assert res.source is not None
        assert res.source.provider == "redhat_ubi"
        assert "ubi9/openjdk-17" in res.base_image

    def test_custom_tier1_sources_only(self):
        config = {
            "default_tier1_provider": "corretto",
            "sources": {
                "corretto": {"tier": 1, "jdk_versions": ["11", "17"]},
            },
        }
        reg = TrustedSourceRegistry(config=config)
        res = reg.resolve_trusted_jdk("17")
        assert res.resolution_type == "exact"
        assert res.source is not None
        assert res.source.provider == "corretto"

    def test_tier2_source_not_used_for_exact(self):
        config = {
            "default_tier1_provider": "corretto",
            "sources": {
                "corretto": {"tier": 2, "jdk_versions": ["11", "17"]},
            },
        }
        reg = TrustedSourceRegistry(config=config)
        res = reg.resolve_trusted_jdk("17")
        assert res.resolution_type == "substituted"
