"""Tests for the Python v3 pipeline."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from buildroot.agent.models import EvalResult
from buildroot.agent.prepass import PrePassFinding
from buildroot.agent.prepass_python import PyPrePassFindings
from buildroot.agent.pipeline_v3_python import (
    BUILDROOT_PYTHON_SCHEMA,
    build_spec_from_values,
    _fallback_values_from_prepass,
    run_v3_pipeline_python,
)
from buildroot.pipeline.models_python import PyProjectData


# ---------------------------------------------------------------------------
# TestBuildSpecFromValues
# ---------------------------------------------------------------------------


class TestBuildSpecFromValues:
    def _make_findings(self) -> PyPrePassFindings:
        findings = PyPrePassFindings()
        findings.pyproject_data = PyProjectData(
            name="requests",
            version="2.31.0",
            build_backend="setuptools.build_meta",
            build_requires=["setuptools>=64"],
        )
        return findings

    def test_basic_spec_construction(self):
        findings = self._make_findings()
        values = {
            "source_repo": "https://github.com/psf/requests",
            "git_tag": "v2.31.0",
            "python_version": "3.11",
            "build_backend": "setuptools",
            "build_command": "python -m build --sdist",
        }
        spec = build_spec_from_values(values, findings, "requests==2.31.0")

        assert spec.source_repo == "https://github.com/psf/requests"
        assert spec.git_tag == "v2.31.0"
        assert spec.build_backend == "setuptools"
        assert spec.build_command == "python -m build --sdist"
        assert spec.python_spec.version == "3.11"
        assert spec.python_spec.base_image == "python:3.11-slim"
        assert spec.python_spec.needs_build_tools is False
        assert spec.pyproject_data.name == "requests"
        assert spec.pyproject_data.version == "2.31.0"

    def test_c_extensions_use_bookworm(self):
        findings = self._make_findings()
        findings.pyproject_data.has_c_extensions = True
        values = {
            "source_repo": "https://github.com/example/cffi",
            "git_tag": "v1.0.0",
            "python_version": "3.12",
            "build_backend": "setuptools",
            "build_command": "python -m build --sdist",
        }
        spec = build_spec_from_values(values, findings, "cffi==1.0.0")

        assert spec.python_spec.base_image == "python:3.12-bookworm"
        assert spec.python_spec.needs_build_tools is True

    def test_system_packages_trigger_bookworm(self):
        findings = self._make_findings()
        values = {
            "source_repo": "https://github.com/example/pkg",
            "git_tag": "v1.0.0",
            "python_version": "3.11",
            "build_backend": "setuptools",
            "build_command": "python -m build --sdist",
            "system_packages": ["build-essential", "libffi-dev"],
        }
        spec = build_spec_from_values(values, findings, "pkg==1.0.0")

        assert spec.python_spec.base_image == "python:3.11-bookworm"
        assert spec.python_spec.needs_build_tools is True
        assert spec.system_packages == ["build-essential", "libffi-dev"]

    def test_defaults_for_missing_values(self):
        findings = self._make_findings()
        values = {}
        spec = build_spec_from_values(values, findings, "pkg==1.0.0")

        assert spec.source_repo == ""
        assert spec.build_backend == "setuptools"
        assert spec.build_command == "python -m build --sdist"
        assert spec.python_spec.version == "3.11"

    def test_env_vars_passed_through(self):
        findings = self._make_findings()
        values = {
            "env_vars": {"SOURCE_DATE_EPOCH": "0", "CUSTOM": "yes"},
        }
        spec = build_spec_from_values(values, findings, "pkg==1.0.0")

        assert spec.env_vars == {"SOURCE_DATE_EPOCH": "0", "CUSTOM": "yes"}

    def test_pre_post_build_commands(self):
        findings = self._make_findings()
        values = {
            "pre_build_commands": ["echo pre"],
            "post_build_commands": ["echo post"],
        }
        spec = build_spec_from_values(values, findings, "pkg==1.0.0")

        assert spec.pre_build_commands == ["echo pre"]
        assert spec.post_build_commands == ["echo post"]


# ---------------------------------------------------------------------------
# TestFallbackValuesFromPrepass
# ---------------------------------------------------------------------------


class TestFallbackValuesFromPrepass:
    def test_with_all_findings(self):
        findings = PyPrePassFindings()
        findings.source_repo = PrePassFinding(
            value="https://github.com/psf/requests",
            source="pypi_metadata",
            confidence="high",
            evidence="project_urls",
        )
        findings.git_tag = PrePassFinding(
            value="v2.31.0",
            source="github_api",
            confidence="high",
            evidence="tags API",
        )
        findings.python_version = PrePassFinding(
            value="3.12",
            source="resolver",
            confidence="medium",
            evidence="requires-python",
        )
        findings.build_backend = PrePassFinding(
            value="setuptools",
            source="pyproject_toml",
            confidence="high",
            evidence="build-backend",
        )
        findings.build_command = PrePassFinding(
            value="python -m build --sdist",
            source="inferred",
            confidence="medium",
            evidence="default for setuptools",
        )
        findings.env_vars = {"SOURCE_DATE_EPOCH": "0"}

        values = _fallback_values_from_prepass(findings)

        assert values["source_repo"] == "https://github.com/psf/requests"
        assert values["git_tag"] == "v2.31.0"
        assert values["python_version"] == "3.12"
        assert values["build_backend"] == "setuptools"
        assert values["build_command"] == "python -m build --sdist"
        assert values["env_vars"] == {"SOURCE_DATE_EPOCH": "0"}
        assert values["system_packages"] == []
        assert values["extra_build_deps"] == []

    def test_with_no_findings(self):
        findings = PyPrePassFindings()
        values = _fallback_values_from_prepass(findings)

        assert values["source_repo"] == ""
        assert values["git_tag"] == ""
        assert values["python_version"] == "3.11"
        assert values["build_backend"] == "setuptools"
        assert values["build_command"] == "python -m build --sdist"
        assert values["env_vars"] == {}


# ---------------------------------------------------------------------------
# TestPipelineSchema
# ---------------------------------------------------------------------------


class TestPipelineSchema:
    def test_schema_is_valid_json_schema(self):
        """BUILDROOT_PYTHON_SCHEMA should be a valid JSON Schema object."""
        assert BUILDROOT_PYTHON_SCHEMA["type"] == "object"
        assert "properties" in BUILDROOT_PYTHON_SCHEMA
        assert "required" in BUILDROOT_PYTHON_SCHEMA

    def test_required_fields_present_in_properties(self):
        required = BUILDROOT_PYTHON_SCHEMA["required"]
        properties = BUILDROOT_PYTHON_SCHEMA["properties"]
        for field in required:
            assert field in properties, f"Required field {field!r} not in properties"

    def test_build_backend_enum(self):
        backend_prop = BUILDROOT_PYTHON_SCHEMA["properties"]["build_backend"]
        assert "enum" in backend_prop
        assert "setuptools" in backend_prop["enum"]
        assert "poetry" in backend_prop["enum"]
        assert "maturin" in backend_prop["enum"]

    def test_schema_serializable(self):
        """Schema should be JSON-serializable."""
        serialized = json.dumps(BUILDROOT_PYTHON_SCHEMA)
        deserialized = json.loads(serialized)
        assert deserialized == BUILDROOT_PYTHON_SCHEMA


# ---------------------------------------------------------------------------
# TestRunV3PipelinePython
# ---------------------------------------------------------------------------


class TestRunV3PipelinePython:
    """Test the full pipeline with mocked prepass and evaluator."""

    @patch("buildroot.agent.pipeline_v3_python.RecipeStore")
    @patch("buildroot.agent.pipeline_v3_python.Evaluator")
    @patch("buildroot.agent.pipeline_v3_python.run_python_prepass")
    def test_full_pipeline_flow(
        self, mock_prepass, mock_evaluator_cls, mock_recipe_cls, tmp_path
    ):
        # Set up prepass findings
        findings = PyPrePassFindings()
        findings.pyproject_data = PyProjectData(
            name="requests",
            version="2.31.0",
            build_backend="setuptools.build_meta",
            build_requires=["setuptools>=64"],
        )
        findings.source_repo = PrePassFinding(
            value="https://github.com/psf/requests",
            source="pypi_metadata",
            confidence="high",
            evidence="project_urls",
        )
        findings.git_tag = PrePassFinding(
            value="v2.31.0",
            source="github_api",
            confidence="high",
            evidence="tags API",
        )
        findings.build_backend = PrePassFinding(
            value="setuptools",
            source="pyproject_toml",
            confidence="high",
            evidence="build-backend",
        )
        findings.build_command = PrePassFinding(
            value="python -m build --sdist",
            source="inferred",
            confidence="medium",
            evidence="default",
        )
        findings.python_version = PrePassFinding(
            value="3.11",
            source="resolver",
            confidence="medium",
            evidence="requires-python",
        )
        findings.base_image = PrePassFinding(
            value="python:3.11-slim",
            source="resolver",
            confidence="medium",
            evidence="base image",
        )
        mock_prepass.return_value = findings

        # Set up evaluator mock
        eval_result = EvalResult()
        eval_result.l1_parse = True
        eval_result.l2_build = True
        eval_result.l3_command = True
        eval_result.l4_match = False
        eval_result.l4_score = 0.85
        eval_result.reward = 0.925
        eval_result.level_reached = 3
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_python.return_value = eval_result
        mock_evaluator_cls.return_value = mock_evaluator

        # Set up recipe store mock
        mock_recipe = MagicMock()
        mock_recipe_cls.return_value = mock_recipe

        workspace = tmp_path / "workspace"
        result = run_v3_pipeline_python(
            "requests==2.31.0",
            workspace,
            host="test-host",
        )

        assert result["coordinate"] == "requests==2.31.0"
        assert result["reward"] == 0.925
        assert result["level_reached"] == 3
        assert result["l4_score"] == 0.85
        assert "containerfile" in result
        assert "findings" in result

        # Verify prepass was called
        mock_prepass.assert_called_once_with("requests==2.31.0", workspace)

        # Verify evaluator was called
        mock_evaluator.evaluate_python.assert_called_once()
        call_args = mock_evaluator.evaluate_python.call_args
        assert call_args[0][1] == "requests==2.31.0"

        # Verify recipe was saved
        mock_recipe.save.assert_called_once()

    @patch("buildroot.agent.pipeline_v3_python.RecipeStore")
    @patch("buildroot.agent.pipeline_v3_python.Evaluator")
    @patch("buildroot.agent.pipeline_v3_python.run_python_prepass")
    def test_pipeline_with_successful_match(
        self, mock_prepass, mock_evaluator_cls, mock_recipe_cls, tmp_path
    ):
        """Test pipeline when L4 match succeeds."""
        findings = PyPrePassFindings()
        findings.pyproject_data = PyProjectData(name="six", version="1.16.0")
        findings.build_backend = PrePassFinding(
            value="setuptools", source="inferred",
            confidence="medium", evidence="default",
        )
        findings.build_command = PrePassFinding(
            value="python -m build --sdist", source="inferred",
            confidence="medium", evidence="default",
        )
        findings.python_version = PrePassFinding(
            value="3.11", source="resolver",
            confidence="medium", evidence="resolver",
        )
        mock_prepass.return_value = findings

        eval_result = EvalResult()
        eval_result.l1_parse = True
        eval_result.l2_build = True
        eval_result.l3_command = True
        eval_result.l4_match = True
        eval_result.l4_score = 1.0
        eval_result.reward = 1.0
        eval_result.level_reached = 4
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_python.return_value = eval_result
        mock_evaluator_cls.return_value = mock_evaluator

        mock_recipe = MagicMock()
        mock_recipe_cls.return_value = mock_recipe

        workspace = tmp_path / "workspace"
        result = run_v3_pipeline_python("six==1.16.0", workspace)

        assert result["reward"] == 1.0
        assert result["level_reached"] == 4
        assert result["l4_score"] == 1.0

    @patch("buildroot.agent.pipeline_v3_python.RecipeStore")
    @patch("buildroot.agent.pipeline_v3_python.Evaluator")
    @patch("buildroot.agent.pipeline_v3_python.run_python_prepass")
    def test_containerfile_is_generated(
        self, mock_prepass, mock_evaluator_cls, mock_recipe_cls, tmp_path
    ):
        """Verify a Containerfile is generated and passed to evaluator."""
        findings = PyPrePassFindings()
        findings.pyproject_data = PyProjectData(name="pkg", version="1.0.0")
        findings.python_version = PrePassFinding(
            value="3.11", source="resolver",
            confidence="medium", evidence="resolver",
        )
        mock_prepass.return_value = findings

        eval_result = EvalResult()
        eval_result.level_reached = 0
        eval_result.reward = 0.0
        eval_result.l4_score = 0.0
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_python.return_value = eval_result
        mock_evaluator_cls.return_value = mock_evaluator

        mock_recipe = MagicMock()
        mock_recipe_cls.return_value = mock_recipe

        workspace = tmp_path / "workspace"
        run_v3_pipeline_python("pkg==1.0.0", workspace)

        # A Containerfile should have been generated and written
        cf_path = workspace / "output" / "Containerfile"
        assert cf_path.exists()

        # The containerfile should have been passed to evaluate_python
        call_args = mock_evaluator.evaluate_python.call_args
        containerfile_arg = call_args[0][0]
        assert len(containerfile_arg) > 0
        assert "FROM" in containerfile_arg
