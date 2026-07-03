"""Tests for dual-variant Containerfile generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from buildroot.generators.containerfile import ContainerfileGenerator
from buildroot.pipeline.models import BuildrootSpec, JdkSpec
from buildroot.trust.dual_variant import DualVariantGenerator
from buildroot.trust.registry import (
    JdkResolutionStrategy,
    TrustedSourceRegistry,
)


def _make_spec(jdk_version: str = "17", base_image: str = "") -> BuildrootSpec:
    return BuildrootSpec(
        jdk_spec=JdkSpec(
            version=jdk_version,
            distribution="temurin",
            base_image=base_image or f"docker.io/eclipse-temurin:{jdk_version}-jdk",
        ),
        source_repo="https://github.com/test/test",
        git_tag="v1.0",
    )


def _mock_generator() -> MagicMock:
    gen = MagicMock(spec=ContainerfileGenerator)

    def side_effect(spec, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        cf = output_dir / "Containerfile"
        cf.write_text(f"FROM {spec.jdk_spec.base_image}\n")
        bj = output_dir / "buildroot.json"
        bj.write_text("{}")
        return cf, bj

    gen.generate.side_effect = side_effect
    return gen


class TestGenerateDualJdk17:
    def test_exact_match_both_variants_generated(self, tmp_path):
        spec = _make_spec("17")
        registry = TrustedSourceRegistry()
        gen = _mock_generator()
        dual = DualVariantGenerator(registry, gen)

        with patch("buildroot.trust.dual_variant.generate_sbom"):
            exact, trusted = dual.generate_dual(spec, tmp_path)

        assert exact.name == "exact"
        assert trusted.name == "trusted"
        assert exact.jdk_version == "17"
        assert trusted.jdk_version == "17"
        assert trusted.provenance_tier == 1
        assert gen.generate.call_count == 2


class TestGenerateDualJdk9:
    def test_substituted_to_11(self, tmp_path):
        spec = _make_spec("9", base_image="some-jdk9-image")
        registry = TrustedSourceRegistry()
        gen = _mock_generator()
        dual = DualVariantGenerator(registry, gen)

        with patch("buildroot.trust.dual_variant.generate_sbom"):
            exact, trusted = dual.generate_dual(spec, tmp_path)

        assert exact.jdk_version == "9"
        assert trusted.jdk_version == "11"
        assert trusted.provenance_tier is not None
        assert trusted.base_image != ""


class TestCloneSpecDeepCopy:
    def test_original_not_mutated(self, tmp_path):
        spec = _make_spec("9", base_image="original-image")
        original_version = spec.jdk_spec.version
        original_image = spec.jdk_spec.base_image

        registry = TrustedSourceRegistry()
        gen = _mock_generator()
        dual = DualVariantGenerator(registry, gen)

        with patch("buildroot.trust.dual_variant.generate_sbom"):
            dual.generate_dual(spec, tmp_path)

        assert spec.jdk_spec.version == original_version
        assert spec.jdk_spec.base_image == original_image


class TestTrustedVariantHasProvenance:
    def test_provenance_fields_set(self, tmp_path):
        spec = _make_spec("17")
        registry = TrustedSourceRegistry()
        gen = _mock_generator()
        dual = DualVariantGenerator(registry, gen)

        with patch("buildroot.trust.dual_variant.generate_sbom"):
            _, trusted = dual.generate_dual(spec, tmp_path)

        assert trusted.provenance_tier is not None
        assert trusted.jdk_source in ("adoptium", "redhat_ubi")

        trusted_spec_call = gen.generate.call_args_list[1]
        trusted_spec_arg = trusted_spec_call[0][0]
        assert trusted_spec_arg.provenance_tier is not None
        assert trusted_spec_arg.provenance_provider != ""
        assert len(trusted_spec_arg.provenance_verification) > 0


class TestTrustedVariantUsesTemplate:
    def test_template_set_to_trusted_base(self, tmp_path):
        spec = _make_spec("17")
        registry = TrustedSourceRegistry()
        gen = _mock_generator()
        dual = DualVariantGenerator(registry, gen)

        with patch("buildroot.trust.dual_variant.generate_sbom"):
            dual.generate_dual(spec, tmp_path)

        trusted_spec_arg = gen.generate.call_args_list[1][0][0]
        assert trusted_spec_arg.template_id == "trusted_base.j2"


class TestUnavailableResolution:
    def test_unavailable_returns_empty_trusted(self, tmp_path):
        spec = _make_spec("99")
        registry = TrustedSourceRegistry()
        gen = _mock_generator()
        dual = DualVariantGenerator(registry, gen)

        with patch("buildroot.trust.dual_variant.generate_sbom"):
            exact, trusted = dual.generate_dual(
                spec, tmp_path,
                strategy=JdkResolutionStrategy.EXACT_ONLY,
            )

        assert exact.name == "exact"
        assert trusted.name == "trusted"
        assert trusted.jdk_source == "unavailable"
        assert trusted.provenance_tier is None
        assert gen.generate.call_count == 1
