"""Tests for Python version inference with priority heuristic."""

from __future__ import annotations

from buildroot.pipeline.models import CIData, Source
from buildroot.pipeline.models_python import PyProjectData
from buildroot.resolvers.python_version import PythonVersionResolver


def _py_data(
    requires_python: str = "",
    classifiers: list[str] | None = None,
    has_c_extensions: bool = False,
) -> PyProjectData:
    return PyProjectData(
        requires_python=requires_python,
        classifiers=classifiers or [],
        has_c_extensions=has_c_extensions,
    )


class TestPythonRequiresSignal:
    def test_gte_specifier(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(requires_python=">=3.9"))
        assert spec.version == "3.9"
        assert spec.confidence.level == Source.OBSERVED

    def test_eq_specifier(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(requires_python="==3.10"))
        assert spec.version == "3.10"

    def test_compat_specifier(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(requires_python="~=3.11"))
        assert spec.version == "3.11"

    def test_combined_specifier(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(requires_python=">=3.8,<4"))
        assert spec.version == "3.8"

    def test_bare_version(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(requires_python="3.12"))
        assert spec.version == "3.12"


class TestCISetupPython:
    def test_ci_env_var(self):
        ci = CIData(env_vars={"_buildroot_python_version": "3.10"})
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(), ci)
        assert spec.version == "3.10"
        assert spec.confidence.level == Source.OBSERVED

    def test_requires_python_beats_ci(self):
        ci = CIData(env_vars={"_buildroot_python_version": "3.10"})
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(requires_python=">=3.11"), ci)
        assert spec.version == "3.11"


class TestPythonVersionFile:
    def test_simple_version(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(), python_version_file="3.10.12\n")
        assert spec.version == "3.10"
        assert spec.confidence.level == Source.OBSERVED

    def test_empty_file(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(), python_version_file="")
        assert spec.version == "3.11"

    def test_python_version_beats_ci(self):
        ci = CIData(env_vars={"_buildroot_python_version": "3.9"})
        resolver = PythonVersionResolver()
        spec = resolver.resolve(
            _py_data(), ci, python_version_file="3.12.1\n"
        )
        assert spec.version == "3.12"


class TestClassifierSignal:
    def test_picks_highest_version(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(classifiers=[
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.11",
        ]))
        assert spec.version == "3.11"
        assert spec.confidence.level == Source.INFERRED

    def test_ignores_non_version_classifiers(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
        ]))
        assert spec.version == "3.11"
        assert spec.confidence.level == Source.DEFAULTED


class TestDefault:
    def test_no_signals_defaults_to_311(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data())
        assert spec.version == "3.11"
        assert spec.confidence.level == Source.DEFAULTED

    def test_default_image_is_slim(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data())
        assert spec.base_image == "docker.io/library/python:3.11-slim"


class TestConflictDetection:
    def test_conflicting_signals(self):
        ci = CIData(env_vars={"_buildroot_python_version": "3.10"})
        resolver = PythonVersionResolver()
        spec = resolver.resolve(
            _py_data(requires_python=">=3.12"), ci
        )
        assert spec.version == "3.12"
        assert len(spec.conflicts) > 0
        versions_in_conflicts = [c["version"] for c in spec.conflicts]
        assert "3.12" in versions_in_conflicts
        assert "3.10" in versions_in_conflicts

    def test_no_conflict_when_agreeing(self):
        ci = CIData(env_vars={"_buildroot_python_version": "3.11"})
        resolver = PythonVersionResolver()
        spec = resolver.resolve(
            _py_data(requires_python=">=3.11"), ci
        )
        assert len(spec.conflicts) == 0


class TestImageMapping:
    def test_pure_python_gets_slim(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(_py_data(requires_python=">=3.10"))
        assert spec.base_image == "docker.io/library/python:3.10-slim"

    def test_c_extensions_get_bookworm(self):
        resolver = PythonVersionResolver()
        spec = resolver.resolve(
            _py_data(requires_python=">=3.10", has_c_extensions=True)
        )
        assert spec.base_image == "docker.io/library/python:3.10-bookworm"
        assert spec.needs_build_tools is True


class TestToxBasepython:
    def test_tox_basepython(self):
        resolver = PythonVersionResolver()
        tox_content = "[testenv]\nbasepython = python3.9\n"
        spec = resolver.resolve(_py_data(), tox_ini_content=tox_content)
        assert spec.version == "3.9"
        assert spec.confidence.level == Source.INFERRED


class TestToolVersions:
    def test_tool_versions_file(self):
        resolver = PythonVersionResolver()
        content = "nodejs 18.0.0\npython 3.10.4\n"
        spec = resolver.resolve(_py_data(), tool_versions_file=content)
        assert spec.version == "3.10"
        assert spec.confidence.level == Source.OBSERVED
