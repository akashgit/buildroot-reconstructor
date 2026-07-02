"""Dual-variant Containerfile generation (exact + trusted)."""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from buildroot.generators.containerfile import ContainerfileGenerator
from buildroot.pipeline.models import BuildrootSpec
from buildroot.trust.delta import VariantResult
from buildroot.trust.registry import (
    JdkResolutionStrategy,
    TrustedJdkResolution,
    TrustedSourceRegistry,
)
from buildroot.trust.sbom import generate_sbom

logger = logging.getLogger(__name__)


class DualVariantGenerator:
    """Generate both exact and trusted-source Containerfile variants."""

    def __init__(
        self,
        registry: TrustedSourceRegistry,
        generator: ContainerfileGenerator,
    ) -> None:
        self._registry = registry
        self._generator = generator

    def generate_dual(
        self,
        spec: BuildrootSpec,
        output_dir: Path,
        strategy: JdkResolutionStrategy = JdkResolutionStrategy.NEAREST_LTS_ABOVE,
    ) -> tuple[VariantResult, VariantResult]:
        exact_dir = output_dir / "exact"
        trusted_dir = output_dir / "trusted"

        cf_path, json_path = self._generator.generate(spec, exact_dir)
        exact_result = VariantResult(
            name="exact",
            containerfile_path=cf_path,
            buildroot_json_path=json_path,
            base_image=spec.jdk_spec.base_image,
            jdk_version=spec.jdk_spec.version,
            jdk_source=spec.jdk_spec.source_description or "pipeline",
            provenance_tier=spec.provenance_tier,
        )
        generate_sbom(spec, "exact", exact_dir)

        resolution = self._registry.resolve_trusted_jdk(
            spec.jdk_spec.version, strategy
        )

        if resolution.resolution_type == "unavailable":
            logger.warning(
                "No trusted JDK resolution for %s; trusted variant skipped",
                spec.jdk_spec.version,
            )
            trusted_result = VariantResult(
                name="trusted",
                base_image="",
                jdk_version=spec.jdk_spec.version,
                jdk_source="unavailable",
                provenance_tier=None,
            )
            return exact_result, trusted_result

        trusted_spec = self._clone_spec(spec)
        trusted_spec.jdk_spec.version = resolution.resolved_version
        trusted_spec.jdk_spec.base_image = resolution.base_image
        trusted_spec.template_id = "trusted_base.j2"
        trusted_spec.jdk_resolution_type = resolution.resolution_type
        trusted_spec.jdk_requested_version = resolution.requested_version

        if resolution.source:
            trusted_spec.provenance_tier = resolution.source.tier.value
            trusted_spec.provenance_provider = resolution.source.provider
            trusted_spec.provenance_verification = list(
                resolution.source.verification
            )
            trusted_spec.trusted_base_image = resolution.base_image

        cf_path_t, json_path_t = self._generator.generate(trusted_spec, trusted_dir)
        trusted_result = VariantResult(
            name="trusted",
            containerfile_path=cf_path_t,
            buildroot_json_path=json_path_t,
            base_image=resolution.base_image,
            jdk_version=resolution.resolved_version,
            jdk_source=resolution.source.provider if resolution.source else "",
            provenance_tier=(
                resolution.source.tier.value if resolution.source else None
            ),
        )
        generate_sbom(trusted_spec, "trusted", trusted_dir)

        logger.info(
            "Generated dual variants: exact (JDK %s) + trusted (JDK %s from %s)",
            spec.jdk_spec.version,
            resolution.resolved_version,
            resolution.source.provider if resolution.source else "unknown",
        )

        return exact_result, trusted_result

    def _clone_spec(self, spec: BuildrootSpec) -> BuildrootSpec:
        return copy.deepcopy(spec)
