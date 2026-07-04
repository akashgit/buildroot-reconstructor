"""Tests for JdkResolver.resolve_trusted() method."""

from __future__ import annotations

from buildroot.resolvers.jdk import TRUSTED_IMAGE_MAP, JdkResolver
from buildroot.trust.registry import (
    JdkResolutionStrategy,
    TrustedSourceRegistry,
)


class TestResolveTrusted:
    def test_jdk17_exact_match(self):
        resolver = JdkResolver()
        registry = TrustedSourceRegistry()
        res = resolver.resolve_trusted("17", registry)
        assert res.resolution_type == "exact"
        assert res.resolved_version == "17"
        assert "openjdk" in res.base_image or "temurin" in res.base_image

    def test_jdk9_substituted_to_11(self):
        resolver = JdkResolver()
        registry = TrustedSourceRegistry()
        res = resolver.resolve_trusted("9", registry)
        assert res.resolution_type == "substituted"
        assert res.resolved_version == "11"
        assert "temurin" in res.base_image or "ubi" in res.base_image

    def test_jdk9_build_from_source(self):
        resolver = JdkResolver()
        registry = TrustedSourceRegistry()
        res = resolver.resolve_trusted(
            "9", registry, strategy=JdkResolutionStrategy.BUILD_FROM_SOURCE
        )
        assert res.resolution_type == "build_from_source"

    def test_jdk9_exact_only_unavailable(self):
        resolver = JdkResolver()
        registry = TrustedSourceRegistry()
        res = resolver.resolve_trusted(
            "9", registry, strategy=JdkResolutionStrategy.EXACT_ONLY
        )
        assert res.resolution_type == "unavailable"

    def test_with_ubi_provider(self):
        resolver = JdkResolver()
        registry = TrustedSourceRegistry(config={
            "default_tier1_provider": "redhat_ubi",
            "sources": {
                "redhat_ubi": {"tier": 1, "jdk_versions": ["11", "17", "21", "25"]},
            },
        })
        res = resolver.resolve_trusted("17", registry)
        assert res.resolution_type == "exact"
        assert "ubi9/openjdk-17" in res.base_image

    def test_ubi_jdk11_maps_to_ubi8(self):
        resolver = JdkResolver()
        registry = TrustedSourceRegistry(config={
            "default_tier1_provider": "redhat_ubi",
            "sources": {
                "redhat_ubi": {"tier": 1, "jdk_versions": ["11", "17", "21", "25"]},
            },
        })
        res = resolver.resolve_trusted("11", registry)
        assert "ubi8/openjdk-11" in res.base_image


class TestTrustedImageMap:
    def test_adoptium_pattern(self):
        pattern = TRUSTED_IMAGE_MAP["adoptium"]
        assert pattern.format(version="17") == "registry.access.redhat.com/ubi9/openjdk-17"

    def test_redhat_ubi_pattern(self):
        pattern = TRUSTED_IMAGE_MAP["redhat_ubi"]
        assert pattern.format(version="17") == "registry.access.redhat.com/ubi9/openjdk-17"

    def test_redhat_ubi_11_pattern(self):
        pattern = TRUSTED_IMAGE_MAP["redhat_ubi_11"]
        assert pattern.format(version="11") == "registry.access.redhat.com/ubi8/openjdk-11"

    def test_corretto_pattern(self):
        pattern = TRUSTED_IMAGE_MAP["corretto"]
        assert pattern.format(version="17") == "docker.io/amazoncorretto:17"


class TestIntegrationStandardAndTrusted:
    def test_different_base_images_for_jdk9(self):
        from buildroot.pipeline.models import PomData

        resolver = JdkResolver()
        registry = TrustedSourceRegistry()

        standard = resolver.resolve(
            PomData(), None, {"maven.compiler.release": "9"}
        )
        trusted = resolver.resolve_trusted("9", registry)

        assert standard.version == "9"
        assert trusted.resolved_version == "11"
        assert standard.base_image != trusted.base_image

    def test_same_version_different_images(self):
        from buildroot.pipeline.models import PomData

        resolver = JdkResolver()
        registry = TrustedSourceRegistry()

        standard = resolver.resolve(
            PomData(), None, {"maven.compiler.release": "17"}
        )
        trusted = resolver.resolve_trusted("17", registry)

        assert standard.version == "17"
        assert trusted.resolved_version == "17"
        assert trusted.resolution_type == "exact"
