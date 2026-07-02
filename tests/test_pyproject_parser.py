"""Tests for Python project configuration parsing."""

from __future__ import annotations

from buildroot.parsers.pyproject import PyProjectParser

SETUPTOOLS_TOML = """\
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-package"
version = "1.0.0"
requires-python = ">=3.9"
dependencies = ["requests>=2.28", "click"]
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
]

[project.urls]
Homepage = "https://example.com"
Source = "https://github.com/example/my-package"

[project.scripts]
my-cli = "my_package.cli:main"
"""

POETRY_TOML = """\
[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"

[tool.poetry]
name = "poetry-project"
version = "2.0.0"

[tool.poetry.dependencies]
python = "^3.10"
httpx = ">=0.24"
"""

FLIT_TOML = """\
[build-system]
requires = ["flit_core>=3.4"]
build-backend = "flit_core.buildapi"

[project]
name = "flit-project"
version = "0.1.0"
"""

HATCH_TOML = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "hatch-project"
version = "3.0.0"
"""

MATURIN_TOML = """\
[build-system]
requires = ["maturin>=1.0"]
build-backend = "maturin"

[project]
name = "rust-ext"
version = "0.1.0"
"""

SCIKIT_BUILD_TOML = """\
[build-system]
requires = ["scikit-build-core>=0.5"]
build-backend = "scikit_build_core.build"

[project]
name = "native-ext"
version = "0.2.0"
"""

SETUP_CFG = """\
[metadata]
name = cfg-package
version = 2.0.0
classifiers =
    Programming Language :: Python :: 3
    Programming Language :: Python :: 3.10

[options]
python_requires = >=3.8
install_requires =
    flask>=2.0
    sqlalchemy

[options.extras_require]
dev =
    pytest
    black

[options.entry_points]
console_scripts =
    cfg-cli = cfg_package.main:run
"""

SETUP_PY = """\
from setuptools import setup, find_packages

setup(
    name="legacy-package",
    version="0.5.0",
    python_requires=">=3.7",
    install_requires=["numpy", "pandas>=1.5"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
    ],
    package_dir={"": "src"},
)
"""

SETUP_PY_WITH_EXT = """\
from setuptools import setup, Extension

setup(
    name="ext-package",
    version="1.0.0",
    ext_modules=[Extension("ext", sources=["ext.c"])],
)
"""


class TestParsePyprojectToml:
    def test_setuptools_config(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(SETUPTOOLS_TOML)
        assert proj.name == "my-package"
        assert proj.version == "1.0.0"
        assert proj.requires_python == ">=3.9"
        assert proj.build_backend == "setuptools.build_meta"
        assert "setuptools>=68.0" in proj.build_requires
        assert "requests>=2.28" in proj.dependencies
        assert proj.project_urls["Homepage"] == "https://example.com"
        assert proj.scripts["my-cli"] == "my_package.cli:main"

    def test_poetry_config(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(POETRY_TOML)
        assert proj.name == "poetry-project"
        assert proj.version == "2.0.0"
        assert proj.build_backend == "poetry.core.masonry.api"
        assert proj.requires_python == "^3.10"

    def test_flit_config(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(FLIT_TOML)
        assert proj.name == "flit-project"
        assert proj.build_backend == "flit_core.buildapi"

    def test_hatch_config(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(HATCH_TOML)
        assert proj.name == "hatch-project"
        assert proj.build_backend == "hatchling.build"


class TestParseSetupCfg:
    def test_basic_metadata(self):
        parser = PyProjectParser()
        proj = parser.parse_setup_cfg(SETUP_CFG)
        assert proj.name == "cfg-package"
        assert proj.version == "2.0.0"
        assert proj.requires_python == ">=3.8"
        assert "flask>=2.0" in proj.dependencies
        assert "sqlalchemy" in proj.dependencies

    def test_extras(self):
        parser = PyProjectParser()
        proj = parser.parse_setup_cfg(SETUP_CFG)
        assert "dev" in proj.optional_dependencies
        assert "pytest" in proj.optional_dependencies["dev"]

    def test_entry_points(self):
        parser = PyProjectParser()
        proj = parser.parse_setup_cfg(SETUP_CFG)
        assert proj.scripts["cfg-cli"] == "cfg_package.main:run"


class TestParseSetupPy:
    def test_basic_extraction(self):
        parser = PyProjectParser()
        proj = parser.parse_setup_py(SETUP_PY)
        assert proj.name == "legacy-package"
        assert proj.version == "0.5.0"
        assert proj.requires_python == ">=3.7"
        assert "numpy" in proj.dependencies
        assert proj.package_dir == "src"

    def test_c_extension_detection(self):
        parser = PyProjectParser()
        proj = parser.parse_setup_py(SETUP_PY_WITH_EXT)
        assert proj.has_c_extensions is True

    def test_syntax_error_returns_empty(self):
        parser = PyProjectParser()
        proj = parser.parse_setup_py("this is not valid python !!!")
        assert proj.name == ""


class TestDetectBuildSystem:
    def test_setuptools(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(SETUPTOOLS_TOML)
        assert parser.detect_build_system(proj) == "setuptools"

    def test_poetry(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(POETRY_TOML)
        assert parser.detect_build_system(proj) == "poetry"

    def test_flit(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(FLIT_TOML)
        assert parser.detect_build_system(proj) == "flit"

    def test_hatch(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(HATCH_TOML)
        assert parser.detect_build_system(proj) == "hatch"

    def test_maturin(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(MATURIN_TOML)
        assert parser.detect_build_system(proj) == "maturin"

    def test_scikit_build(self):
        parser = PyProjectParser()
        proj = parser.parse_pyproject_toml(SCIKIT_BUILD_TOML)
        assert parser.detect_build_system(proj) == "scikit-build"

    def test_unknown_backend(self):
        parser = PyProjectParser()
        from buildroot.pipeline.models_python import PyProjectData
        proj = PyProjectData(build_backend="some.custom.backend")
        assert parser.detect_build_system(proj) == "unknown"


class TestDetectCExtensions:
    def test_from_file_list(self):
        parser = PyProjectParser()
        from buildroot.pipeline.models_python import PyProjectData
        proj = PyProjectData()
        assert parser.detect_c_extensions(proj, ["src/main.py"]) is False
        assert parser.detect_c_extensions(proj, ["src/ext.c", "src/main.py"]) is True

    def test_from_build_requires(self):
        parser = PyProjectParser()
        from buildroot.pipeline.models_python import PyProjectData
        proj = PyProjectData(build_requires=["cython>=3.0"])
        assert parser.detect_c_extensions(proj, []) is True

    def test_from_has_c_extensions_flag(self):
        parser = PyProjectParser()
        from buildroot.pipeline.models_python import PyProjectData
        proj = PyProjectData(has_c_extensions=True)
        assert parser.detect_c_extensions(proj, []) is True


class TestMergeConfigs:
    def test_pyproject_takes_priority(self):
        parser = PyProjectParser()
        pyproject = parser.parse_pyproject_toml(SETUPTOOLS_TOML)
        setup_cfg = parser.parse_setup_cfg(SETUP_CFG)
        merged = parser.merge_configs(pyproject, setup_cfg, None)
        assert merged.name == "my-package"
        assert merged.build_backend == "setuptools.build_meta"

    def test_fallback_to_setup_cfg(self):
        parser = PyProjectParser()
        from buildroot.pipeline.models_python import PyProjectData
        setup_cfg = parser.parse_setup_cfg(SETUP_CFG)
        merged = parser.merge_configs(None, setup_cfg, None)
        assert merged.name == "cfg-package"

    def test_all_none(self):
        parser = PyProjectParser()
        merged = parser.merge_configs(None, None, None)
        assert merged.name == ""
