"""Pipeline v3 for Python packages — agentic build loop for sdist reconstruction."""

from __future__ import annotations

from pathlib import Path

import structlog

from buildroot.agent.evaluator import Evaluator
from buildroot.agent.models import RecipeStore
from buildroot.agent.prepass_python import (
    PyPrePassFindings,
    parse_python_coordinate,
    run_python_prepass,
)
from buildroot.generators.containerfile import ContainerfileGenerator
from buildroot.pipeline.models_python import PyBuildrootSpec, PythonSpec

logger = structlog.get_logger()

# Template values schema for the analysis agent
BUILDROOT_PYTHON_SCHEMA = {
    "type": "object",
    "properties": {
        "source_repo": {"type": "string", "description": "GitHub repository URL"},
        "git_tag": {"type": "string", "description": "Git tag for the version"},
        "python_version": {
            "type": "string",
            "description": "Python version e.g. '3.11'",
        },
        "build_backend": {
            "type": "string",
            "enum": [
                "setuptools",
                "poetry",
                "flit",
                "hatch",
                "maturin",
                "scikit-build",
            ],
            "description": "Python build backend",
        },
        "build_command": {
            "type": "string",
            "description": "Build command e.g. 'python -m build --sdist'",
        },
        "system_packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "apt packages needed for build",
        },
        "pre_build_commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Commands to run before build",
        },
        "post_build_commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Commands to run after build",
        },
        "env_vars": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Environment variables",
        },
        "extra_build_deps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Additional pip packages for build",
        },
    },
    "required": [
        "source_repo",
        "git_tag",
        "python_version",
        "build_backend",
        "build_command",
    ],
}

# System prompt for the Python analysis agent
ANALYSIS_AGENT_SYSTEM_PYTHON = """\
You are a Python packaging expert analyzing a package build.
Your task is to determine the exact build configuration needed to reproduce a Python \
source distribution (sdist).

You will receive pre-pass findings about a Python package. Use them to fill in the \
build template values.

Key considerations:
- Build backend: setuptools, poetry, flit, hatch, maturin, scikit-build
- Python version: must match what was used to build the original
- Build command: usually 'python -m build --sdist' for PEP 517 builds
- SOURCE_DATE_EPOCH=0 for reproducible timestamps
- Some packages need system packages (build-essential for C extensions)
- setuptools-scm packages need full git history (not --depth 1)
- Poetry packages need 'poetry build --format sdist'

Output your analysis as a JSON object matching the required schema.
"""


def build_spec_from_values(
    values: dict,
    findings: PyPrePassFindings,
    coordinate: str,
) -> PyBuildrootSpec:
    """Convert analysis agent output + prepass findings into a PyBuildrootSpec."""
    pkg, ver = parse_python_coordinate(coordinate)

    spec = PyBuildrootSpec()
    spec.pyproject_data = findings.pyproject_data
    spec.pyproject_data.name = pkg
    spec.pyproject_data.version = ver
    spec.source_repo = values.get("source_repo", "")
    spec.git_tag = values.get("git_tag", "")
    spec.build_backend = values.get("build_backend", "setuptools")
    spec.build_command = values.get("build_command", "python -m build --sdist")
    spec.system_packages = values.get("system_packages", [])
    spec.pre_build_commands = values.get("pre_build_commands", [])
    spec.post_build_commands = values.get("post_build_commands", [])
    spec.env_vars = values.get("env_vars", {})

    python_version = values.get("python_version", "3.11")
    needs_build_tools = spec.pyproject_data.has_c_extensions or bool(
        spec.system_packages
    )
    suffix = "bookworm" if needs_build_tools else "slim"
    spec.python_spec = PythonSpec(
        version=python_version,
        base_image=f"python:{python_version}-{suffix}",
        needs_build_tools=needs_build_tools,
    )

    return spec


def run_v3_pipeline_python(
    coordinate: str,
    workspace: Path,
    *,
    host: str = "rh-h100-01",
    max_iterations: int = 10,
    target_score: float = 0.98,
) -> dict:
    """Run the Python v3 pipeline.

    1. Run prepass
    2. Check RecipeStore for warm-start
    3. Generate initial Containerfile from prepass findings
    4. Evaluate
    5. If score < target, iterate with feedback
    6. Save best result to RecipeStore
    7. Return results dict

    This is a simplified version of pipeline_v3.py for Python.
    The full agentic loop (with Claude agents) can be added later.
    For now, this does: prepass -> generate -> evaluate -> return.
    """
    logger.info("python_pipeline_start", coordinate=coordinate, host=host)

    pkg, ver = parse_python_coordinate(coordinate)
    findings = run_python_prepass(coordinate, workspace)

    # Build default values from prepass
    values = _fallback_values_from_prepass(findings)

    # Build spec and generate Containerfile
    spec = build_spec_from_values(values, findings, coordinate)
    gen = ContainerfileGenerator()
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    cf_path, prov_path = gen.generate_python(spec, output_dir)

    containerfile = cf_path.read_text()

    # Evaluate
    evaluator = Evaluator(host=host)
    result = evaluator.evaluate_python(containerfile, coordinate)

    # Save to recipe store
    recipe_store = RecipeStore()
    recipe_store.save(coordinate, result.level_reached, containerfile, result.reward)

    logger.info(
        "python_pipeline_complete",
        coordinate=coordinate,
        reward=result.reward,
        level=result.level_reached,
        l4_score=result.l4_score,
    )

    return {
        "coordinate": coordinate,
        "reward": result.reward,
        "level_reached": result.level_reached,
        "l4_score": result.l4_score,
        "containerfile": containerfile,
        "findings": findings.to_dict(),
    }


def _fallback_values_from_prepass(findings: PyPrePassFindings) -> dict:
    """Extract default template values from prepass findings."""
    values: dict = {}
    if findings.source_repo:
        values["source_repo"] = findings.source_repo.value
    else:
        values["source_repo"] = ""
    if findings.git_tag:
        values["git_tag"] = findings.git_tag.value
    else:
        values["git_tag"] = ""
    if findings.python_version:
        values["python_version"] = findings.python_version.value
    else:
        values["python_version"] = "3.11"
    if findings.build_backend:
        values["build_backend"] = findings.build_backend.value
    else:
        values["build_backend"] = "setuptools"
    if findings.build_command:
        values["build_command"] = findings.build_command.value
    else:
        values["build_command"] = "python -m build --sdist"
    values["system_packages"] = []
    values["pre_build_commands"] = []
    values["post_build_commands"] = []
    values["env_vars"] = dict(findings.env_vars) if findings.env_vars else {}
    values["extra_build_deps"] = []
    return values
