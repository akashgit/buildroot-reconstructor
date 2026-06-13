"""Parse PNC builders-image Containerfiles to extract ground-truth build environment."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from dockerfile_parse import DockerfileParser

logger = logging.getLogger(__name__)

_JDK_RPM_RE = re.compile(
    r"java-(?:(\d+)\.(\d+)\.(\d+)|(\d+))-(\w+)-devel"
)

_MAVEN_URL_RE = re.compile(
    r"apache-maven-(\d+\.\d+(?:\.\d+)?)"
)

_GRADLE_URL_RE = re.compile(
    r"gradle-(\d+\.\d+(?:\.\d+)?)"
)

_RHEL_BASE_RE = re.compile(
    r"(?:rhel|ubi)(\d+)"
)


@dataclass
class PNCGroundTruth:
    """Ground truth extracted from a PNC builders-image Containerfile chain."""

    jdk_major_version: str = ""
    jdk_vendor: str = ""
    build_tool: str = ""
    build_tool_version: str = ""
    os_family: str = ""
    os_version: str = ""
    scm_url: str = ""
    image_name: str = ""
    raw_env: dict[str, str] = field(default_factory=dict)


def _extract_jdk_from_rpms(content: str) -> tuple[str, str]:
    """Extract JDK major version and vendor from RPM install commands."""
    for match in _JDK_RPM_RE.finditer(content):
        if match.group(1):
            major_1, minor, _ = match.group(1), match.group(2), match.group(3)
            vendor = match.group(5)
            if major_1 == "1":
                return minor, vendor
            return major_1, vendor
        else:
            major = match.group(4)
            vendor = match.group(5)
            return major, vendor
    return "", ""


def _extract_build_tool_from_env(env_vars: dict[str, str]) -> tuple[str, str]:
    """Extract build tool and version from ENV variables."""
    for key in ("MAVEN_VERSION", "MVN_VERSION"):
        if key in env_vars:
            return "maven", env_vars[key]

    for key in ("GRADLE_VERSION",):
        if key in env_vars:
            return "gradle", env_vars[key]

    return "", ""


def _extract_build_tool_from_urls(content: str) -> tuple[str, str]:
    """Extract build tool and version from download URLs in RUN commands."""
    maven_match = _MAVEN_URL_RE.search(content)
    if maven_match:
        return "maven", maven_match.group(1)

    gradle_match = _GRADLE_URL_RE.search(content)
    if gradle_match:
        return "gradle", gradle_match.group(1)

    return "", ""


def _extract_rhel_version(base_images: list[str]) -> tuple[str, str]:
    """Extract RHEL family and version from base image references."""
    for image in base_images:
        match = _RHEL_BASE_RE.search(image)
        if match:
            return "rhel", match.group(1)
    return "", ""


def parse_containerfile(content: str) -> dict:
    """Parse a single Containerfile and return extracted info."""
    dfp = DockerfileParser(fileobj=io.BytesIO())
    dfp.content = content

    env_vars = {}
    for env_entry in dfp.envs:
        env_vars[env_entry] = dfp.envs[env_entry]

    base_images = [
        entry["value"] for entry in dfp.structure
        if entry["instruction"] == "FROM"
    ]

    return {
        "base_images": base_images,
        "env_vars": env_vars,
        "content": content,
    }


def parse_pnc_containerfile_chain(
    builders_image_dir: str | Path,
    pnc_image: str,
) -> PNCGroundTruth:
    """Parse a PNC 2-layer Containerfile chain (tool-layer -> base-layer).

    The builders-image directory contains subdirectories named like
    `builder-rhel-7-j8-mvn3.3.9`, each with a Containerfile.
    The tool-layer FROM references a base-layer image.
    """
    base_dir = Path(builders_image_dir)
    image_dir = base_dir / pnc_image

    truth = PNCGroundTruth(image_name=pnc_image)

    containerfile_path = image_dir / "Containerfile"
    if not containerfile_path.exists():
        containerfile_path = image_dir / "Dockerfile"
    if not containerfile_path.exists():
        logger.warning("No Containerfile found in %s", image_dir)
        return truth

    tool_content = containerfile_path.read_text(encoding="utf-8")
    tool_parsed = parse_containerfile(tool_content)

    truth.raw_env.update(tool_parsed["env_vars"])

    build_tool, build_tool_version = _extract_build_tool_from_env(tool_parsed["env_vars"])
    if not build_tool:
        build_tool, build_tool_version = _extract_build_tool_from_urls(tool_content)
    truth.build_tool = build_tool
    truth.build_tool_version = build_tool_version

    jdk_major, jdk_vendor = _extract_jdk_from_rpms(tool_content)

    os_family, os_version = _extract_rhel_version(tool_parsed["base_images"])

    for base_image_ref in tool_parsed["base_images"]:
        base_name = base_image_ref.split("/")[-1].split(":")[0]
        base_candidate = base_dir / base_name
        if base_candidate.is_dir():
            base_cf = base_candidate / "Containerfile"
            if not base_cf.exists():
                base_cf = base_candidate / "Dockerfile"
            if base_cf.exists():
                base_content = base_cf.read_text(encoding="utf-8")
                base_parsed = parse_containerfile(base_content)
                truth.raw_env.update(base_parsed["env_vars"])

                if not jdk_major:
                    jdk_major, jdk_vendor = _extract_jdk_from_rpms(base_content)

                if not os_family:
                    os_family, os_version = _extract_rhel_version(base_parsed["base_images"])

                if not build_tool:
                    bt, btv = _extract_build_tool_from_env(base_parsed["env_vars"])
                    if not bt:
                        bt, btv = _extract_build_tool_from_urls(base_content)
                    truth.build_tool = bt
                    truth.build_tool_version = btv
                break

    if not jdk_major:
        jdk_major, jdk_vendor = _infer_from_image_name(pnc_image)

    if not os_family:
        os_family, os_version = _extract_rhel_version([pnc_image])

    truth.jdk_major_version = jdk_major
    truth.jdk_vendor = jdk_vendor or "openjdk"
    truth.os_family = os_family
    truth.os_version = os_version

    return truth


def _infer_from_image_name(image_name: str) -> tuple[str, str]:
    """Fallback: extract JDK version from the image name pattern like builder-rhel-7-j8-mvn3.3.9."""
    match = re.search(r"-j(\d+)-", image_name)
    if match:
        return match.group(1), "openjdk"
    return "", ""
