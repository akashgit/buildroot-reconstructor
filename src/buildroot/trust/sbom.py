"""CycloneDX 1.5 SBOM generation for buildroot variants."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from buildroot.pipeline.models import BuildrootSpec

logger = logging.getLogger(__name__)

TOOL_NAME = "buildroot-reconstructor"
TOOL_VERSION = "0.1.0"
CYCLONEDX_SPEC_VERSION = "1.5"


def generate_sbom(
    spec: BuildrootSpec, variant_name: str, output_dir: Path
) -> Path:
    components = []

    jdk_version = spec.jdk_spec.version
    base_image = spec.jdk_spec.base_image
    if base_image:
        name_part, _, tag_part = base_image.rpartition(":")
        image_purl = f"pkg:docker/{name_part}@{tag_part}" if name_part else f"pkg:docker/{base_image}"
    else:
        image_purl = ""

    jdk_properties = []
    if spec.provenance_tier is not None:
        jdk_properties.append(
            {"name": "provenance_tier", "value": str(spec.provenance_tier)}
        )
    if spec.provenance_provider:
        jdk_properties.append(
            {"name": "provenance_provider", "value": spec.provenance_provider}
        )

    components.append({
        "type": "library",
        "name": f"openjdk-{jdk_version}",
        "version": jdk_version,
        "purl": image_purl,
        "properties": jdk_properties,
    })

    if spec.maven_version:
        components.append({
            "type": "library",
            "name": "apache-maven",
            "version": spec.maven_version,
        })

    if base_image:
        components.append({
            "type": "container",
            "name": base_image,
            "version": "",
        })

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "tools": [
                {
                    "name": TOOL_NAME,
                    "version": TOOL_VERSION,
                }
            ],
            "component": {
                "type": "application",
                "name": f"buildroot-{variant_name}",
            },
        },
        "components": components,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = output_dir / "sbom.cdx.json"
    sbom_path.write_text(json.dumps(sbom, indent=2) + "\n")
    logger.info("Generated SBOM at %s", sbom_path)
    return sbom_path
