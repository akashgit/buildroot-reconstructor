"""Containerfile generation from BuildrootSpec."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from buildroot.pipeline.models import BuildrootSpec, Source
from buildroot.pipeline.models_python import PyBuildrootSpec

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

RUNNER_IMAGE_MAP = {
    "ubuntu-latest": "24.04",
    "ubuntu-24.04": "24.04",
    "ubuntu-22.04": "22.04",
    "ubuntu-20.04": "20.04",
}

DEFAULT_BUILD_COMMAND = "mvn clean install -B"

_PYTHON_TEMPLATE_MAP = {
    "setuptools": "python_base.j2",
    "flit": "python_base.j2",
    "hatch": "python_base.j2",
    "poetry": "python_poetry.j2",
    "maturin": "python_compiled.j2",
    "scikit-build": "python_compiled.j2",
}

REPRODUCIBLE_FLAGS = [
    "-Dproject.build.outputTimestamp=2000-01-01T00:00:00Z",
]


class ContainerfileGenerator:
    """Generate Containerfile and buildroot.json from a BuildrootSpec."""

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self, spec: BuildrootSpec, output_dir: Path
    ) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        template_name = self._select_template(
            spec, template_id=spec.template_id, build_system=spec.build_system,
        )
        template = self._env.get_template(template_name)

        context = self._build_template_context(spec)
        rendered = template.render(**context)

        containerfile_path = output_dir / "Containerfile"
        containerfile_path.write_text(rendered)

        buildroot_json = self.generate_buildroot_json(spec)
        json_path = output_dir / "buildroot.json"
        json_path.write_text(json.dumps(buildroot_json, indent=2) + "\n")

        logger.info(
            "Generated %s using template %s", containerfile_path, template_name
        )
        return containerfile_path, json_path

    def generate_buildroot_json(self, spec: BuildrootSpec) -> dict:
        jdk_conf = spec.jdk_spec.confidence
        jdk_source = jdk_conf.level.value if jdk_conf else Source.DEFAULTED.value
        jdk_reason = jdk_conf.reason if jdk_conf else "no signal"

        build_command = self._resolve_build_command(spec)
        build_source, build_conf = self._build_command_provenance(spec)

        gap_entries = []
        for entry in spec.gaps.entries:
            gap_entries.append({
                "field": entry.field,
                "status": entry.status,
                "reason": entry.reason,
                "source": entry.source.value,
            })

        deps = []
        if spec.dependency_tree:
            deps = self._flatten_direct_deps(spec.dependency_tree)

        return {
            "source_repo": spec.source_repo,
            "git_tag": spec.git_tag,
            "jdk_version": {
                "value": spec.jdk_spec.version,
                "source": jdk_source,
                "confidence": jdk_reason,
            },
            "jdk_distribution": {
                "value": spec.jdk_spec.distribution,
                "source": jdk_source,
            },
            "maven_version": {
                "value": spec.maven_version or "system-default",
                "source": (
                    Source.OBSERVED.value if spec.maven_version
                    else Source.DEFAULTED.value
                ),
            },
            "build_command": {
                "value": build_command,
                "source": build_source,
                "confidence": build_conf,
            },
            "base_image": {
                "value": spec.jdk_spec.base_image,
                "source": jdk_source,
            },
            "system_packages": spec.system_packages,
            "dependencies": deps,
            "gap_report": gap_entries,
        }

    _BUILD_SYSTEM_TEMPLATE_MAP = {
        "maven": "jdk_base.j2",
        "gradle": "gradle_base.j2",
        "ant": "jdk_base.j2",
        "custom": "custom_base.j2",
    }

    def _select_template(self, spec: BuildrootSpec, *, template_id: str = "", build_system: str = "") -> str:
        if template_id:
            return template_id
        if build_system and build_system in self._BUILD_SYSTEM_TEMPLATE_MAP:
            return self._BUILD_SYSTEM_TEMPLATE_MAP[build_system]
        if spec.base_image:
            return "custom_base.j2"
        build_cmd = spec.build_commands[0] if spec.build_commands else ""
        if self._detect_build_tool(build_cmd) == "gradle":
            return "gradle_base.j2"
        if spec.system_packages:
            return "jdk_on_ubuntu.j2"
        return "jdk_base.j2"

    def _build_template_context(self, spec: BuildrootSpec) -> dict:
        jdk = spec.jdk_spec
        jdk_conf = jdk.confidence
        jdk_source_str = jdk_conf.level.value if jdk_conf else Source.DEFAULTED.value
        jdk_confidence_str = jdk_source_str.upper()
        dist_source = jdk_source_str
        dist_confidence = jdk_confidence_str

        build_command = self._resolve_build_command(spec)
        build_source, build_conf = self._build_command_provenance(spec)

        maven_source = Source.OBSERVED.value if spec.maven_version else Source.DEFAULTED.value
        maven_confidence = maven_source.upper()

        ubuntu_version = self._resolve_ubuntu_version(spec)
        os_source, os_confidence = self._os_provenance(spec)

        env_vars = {}
        if spec.ci_data:
            env_vars = {
                k: v for k, v in spec.ci_data.env_vars.items()
                if not k.startswith("_buildroot_")
            }

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        build_tool = self._detect_build_tool(build_command)

        return {
            "source_repo": spec.source_repo,
            "git_tag": spec.git_tag,
            "timestamp": timestamp,
            "jdk_version": self._normalize_jdk_version(jdk.version),
            "jdk_distribution": jdk.distribution,
            "jdk_source": jdk.source_description or jdk_source_str,
            "jdk_confidence": jdk_confidence_str,
            "dist_source": dist_source,
            "dist_confidence": dist_confidence,
            "base_image": jdk.base_image,
            "maven_version": spec.maven_version,
            "maven_source": maven_source,
            "maven_confidence": maven_confidence,
            "build_command": build_command,
            "build_source": build_source,
            "build_confidence": build_conf,
            "build_tool": build_tool,
            "system_packages": spec.system_packages,
            "ubuntu_version": ubuntu_version,
            "os_source": os_source,
            "os_confidence": os_confidence,
            "env_vars": env_vars,
            "custom_image": spec.base_image,
            "image_source": "CI container reference",
            "image_confidence": Source.OBSERVED.value.upper(),
            "extra_build_flags": spec.extra_build_flags,
            "pre_build_commands": spec.pre_build_commands,
            "post_build_commands": spec.post_build_commands,
            "config_files": spec.config_files,
            "metadata_strip_patterns": spec.metadata_strip_patterns,
            "reproducibility_env": spec.reproducibility_env,
        }

    def _resolve_build_command(self, spec: BuildrootSpec) -> str:
        cmd = spec.build_commands[0] if spec.build_commands else DEFAULT_BUILD_COMMAND
        return self._add_reproducible_flags(cmd)

    @staticmethod
    def _add_reproducible_flags(cmd: str) -> str:
        if ("mvn " not in cmd and not cmd.startswith("mvn")
                and "mvnw " not in cmd and not cmd.startswith("mvnw")
                and not cmd.startswith("./mvnw")):
            return cmd
        for flag in REPRODUCIBLE_FLAGS:
            key = flag.split("=")[0]
            if key not in cmd:
                cmd = cmd + " " + flag
        return cmd

    def _build_command_provenance(self, spec: BuildrootSpec) -> tuple[str, str]:
        if spec.build_commands:
            return Source.OBSERVED.value, Source.OBSERVED.value.upper()
        return Source.DEFAULTED.value, Source.DEFAULTED.value.upper()

    def _resolve_ubuntu_version(self, spec: BuildrootSpec) -> str:
        runner_os = ""
        if spec.ci_data:
            runner_os = spec.ci_data.runner_os

        if runner_os and runner_os in RUNNER_IMAGE_MAP:
            return RUNNER_IMAGE_MAP[runner_os]
        return "24.04"

    def _os_provenance(self, spec: BuildrootSpec) -> tuple[str, str]:
        runner_os = ""
        if spec.ci_data:
            runner_os = spec.ci_data.runner_os

        if runner_os == "ubuntu-latest":
            return "CI runner (ubuntu-latest mapped)", "INFERRED"
        if runner_os in RUNNER_IMAGE_MAP:
            return f"CI runner ({runner_os})", Source.OBSERVED.value.upper()
        return Source.DEFAULTED.value, Source.DEFAULTED.value.upper()

    def _flatten_direct_deps(self, tree) -> list[dict]:
        deps = []
        for child in tree.children:
            deps.append({
                "groupId": child.group_id,
                "artifactId": child.artifact_id,
                "version": child.version,
                "scope": child.scope,
            })
        return deps

    @staticmethod
    def _normalize_jdk_version(version: str) -> str:
        if version.startswith('1.') and len(version) >= 3:
            return version[2:]
        return version

    @staticmethod
    def _detect_build_tool(build_command: str) -> str:
        cmd = build_command.strip()
        if cmd.startswith("ant") or "ant " in cmd:
            return "ant"
        if cmd.startswith("gradle") or "gradle " in cmd or cmd.startswith("./gradlew") or "./gradlew " in cmd:
            return "gradle"
        return "maven"

    def generate_python(
        self, spec: PyBuildrootSpec, output_dir: Path
    ) -> tuple[Path, Path]:
        """Generate Containerfile from a PyBuildrootSpec.

        1. Select template based on spec.build_backend using _PYTHON_TEMPLATE_MAP
        2. If spec has C extensions, use python_compiled.j2 regardless
        3. Build template context from spec fields
        4. Render template
        5. Write Containerfile and buildroot.json to output_dir
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        template_name = _PYTHON_TEMPLATE_MAP.get(
            spec.build_backend, "python_base.j2"
        )
        if spec.pyproject_data.has_c_extensions:
            template_name = "python_compiled.j2"

        context = {
            "coordinate": f"{spec.pyproject_data.name}=={spec.pyproject_data.version}",
            "base_image": spec.python_spec.base_image or "python:3.11-slim",
            "source_repo": spec.source_repo,
            "git_tag": spec.git_tag,
            "system_packages": spec.system_packages,
            "env_vars": spec.env_vars,
            "pre_build_commands": spec.pre_build_commands,
            "post_build_commands": spec.post_build_commands,
            "build_command": spec.build_command or "python -m build --sdist",
            "extra_build_deps": " ".join(spec.pyproject_data.build_requires),
        }

        template = self._env.get_template(template_name)
        containerfile_content = template.render(**context)

        cf_path = output_dir / "Containerfile"
        cf_path.write_text(containerfile_content)

        provenance = self._generate_python_provenance(spec)
        prov_path = output_dir / "buildroot.json"
        prov_path.write_text(json.dumps(provenance, indent=2) + "\n")

        logger.info(
            "Generated %s using template %s", cf_path, template_name
        )
        return cf_path, prov_path

    def _generate_python_provenance(self, spec: PyBuildrootSpec) -> dict:
        """Generate provenance document for a Python build."""
        return {
            "coordinate": f"{spec.pyproject_data.name}=={spec.pyproject_data.version}",
            "ecosystem": "python",
            "python_version": spec.python_spec.version,
            "build_backend": spec.build_backend,
            "source_repo": spec.source_repo,
            "git_tag": spec.git_tag,
            "base_image": spec.python_spec.base_image,
            "build_command": spec.build_command,
        }

    @staticmethod
    def map_runner_to_ubuntu(runner_os: str) -> str:
        return RUNNER_IMAGE_MAP.get(runner_os, "")
