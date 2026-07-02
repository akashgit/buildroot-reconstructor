"""Python project configuration parsing (pyproject.toml, setup.cfg, setup.py)."""

from __future__ import annotations

import ast
import configparser
import logging
import re
import tomllib

from buildroot.pipeline.models_python import PyProjectData

logger = logging.getLogger(__name__)

BUILD_BACKEND_MAP = {
    "setuptools.build_meta": "setuptools",
    "setuptools.build_meta:__legacy__": "setuptools",
    "poetry.core.masonry.api": "poetry",
    "poetry.masonry.api": "poetry",
    "flit_core.buildapi": "flit",
    "flit.buildapi": "flit",
    "hatchling.build": "hatch",
    "maturin": "maturin",
    "scikit_build_core.build": "scikit-build",
}

C_EXTENSION_PATTERNS = re.compile(
    r"\.(c|cpp|cxx|cc|h|hpp|pyx|pxd)$", re.IGNORECASE
)


class PyProjectParser:
    """Parse Python project configuration from multiple sources."""

    def parse_pyproject_toml(self, content: str) -> PyProjectData:
        """Parse pyproject.toml content into PyProjectData."""
        data = tomllib.loads(content)
        proj = PyProjectData()

        build_system = data.get("build-system", {})
        proj.build_backend = build_system.get("build-backend", "")
        proj.build_requires = list(build_system.get("requires", []))

        project = data.get("project", {})
        proj.name = project.get("name", "")
        proj.version = project.get("version", "")
        proj.requires_python = project.get("requires-python", "")
        proj.dependencies = list(project.get("dependencies", []))
        proj.classifiers = list(project.get("classifiers", []))

        optional_deps = project.get("optional-dependencies", {})
        proj.optional_dependencies = {
            k: list(v) for k, v in optional_deps.items()
        }

        scripts = project.get("scripts", {})
        proj.scripts = dict(scripts)

        gui_scripts = project.get("gui-scripts", {})
        entry_points: dict[str, dict[str, str]] = {}
        if gui_scripts:
            entry_points["gui_scripts"] = dict(gui_scripts)

        eps = project.get("entry-points", {})
        for group, entries in eps.items():
            entry_points[group] = dict(entries)
        proj.entry_points = entry_points

        urls = project.get("urls", {})
        proj.project_urls = dict(urls)

        tool = data.get("tool", {})
        poetry_section = tool.get("poetry", {})
        if poetry_section and not proj.name:
            proj.name = poetry_section.get("name", "")
        if poetry_section and not proj.version:
            proj.version = poetry_section.get("version", "")
        if poetry_section and not proj.dependencies:
            poetry_deps = poetry_section.get("dependencies", {})
            proj.dependencies = [
                f"{k}>={v}" if isinstance(v, str) and v != "*" else k
                for k, v in poetry_deps.items()
                if k.lower() != "python"
            ]
            python_req = poetry_deps.get("python") or poetry_deps.get("Python")
            if python_req and not proj.requires_python:
                proj.requires_python = str(python_req)

        setuptools_section = tool.get("setuptools", {})
        pkg_dir = setuptools_section.get("package-dir", {})
        if isinstance(pkg_dir, dict) and "" in pkg_dir:
            proj.package_dir = pkg_dir[""]
        elif isinstance(pkg_dir, dict) and "root" in pkg_dir:
            proj.package_dir = pkg_dir["root"]

        return proj

    def parse_setup_cfg(self, content: str) -> PyProjectData:
        """Parse setup.cfg content into PyProjectData."""
        config = configparser.ConfigParser()
        config.read_string(content)

        proj = PyProjectData()

        if config.has_section("metadata"):
            proj.name = config.get("metadata", "name", fallback="")
            proj.version = config.get("metadata", "version", fallback="")
            proj.classifiers = _parse_multiline(
                config.get("metadata", "classifiers", fallback="")
            )
            proj.project_urls = _parse_mapping(
                config.get("metadata", "project_urls", fallback="")
            )

        if config.has_section("options"):
            proj.requires_python = config.get(
                "options", "python_requires", fallback=""
            )
            proj.dependencies = _parse_multiline(
                config.get("options", "install_requires", fallback="")
            )
            proj.package_dir = config.get(
                "options", "package_dir", fallback=""
            )
            if proj.package_dir.startswith("="):
                proj.package_dir = proj.package_dir.lstrip("= ")

        if config.has_section("options.extras_require"):
            for key in config.options("options.extras_require"):
                proj.optional_dependencies[key] = _parse_multiline(
                    config.get("options.extras_require", key, fallback="")
                )

        if config.has_section("options.entry_points"):
            for group in config.options("options.entry_points"):
                entries = _parse_multiline(
                    config.get("options.entry_points", group, fallback="")
                )
                if group == "console_scripts":
                    proj.scripts = _parse_entry_point_list(entries)
                else:
                    proj.entry_points[group] = _parse_entry_point_list(entries)

        return proj

    def parse_setup_py(self, content: str) -> PyProjectData:
        """Parse setup.py using AST analysis only — never executes the file."""
        proj = PyProjectData()
        try:
            tree = ast.parse(content)
        except SyntaxError:
            logger.warning("Failed to parse setup.py — syntax error")
            return proj

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "setup":
                pass
            elif isinstance(func, ast.Attribute) and func.attr == "setup":
                pass
            else:
                continue

            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            proj.name = _ast_str(kwargs.get("name"))
            proj.version = _ast_str(kwargs.get("version"))
            proj.requires_python = _ast_str(kwargs.get("python_requires"))
            proj.dependencies = _ast_str_list(kwargs.get("install_requires"))
            proj.classifiers = _ast_str_list(kwargs.get("classifiers"))

            setup_requires = _ast_str_list(kwargs.get("setup_requires"))
            if setup_requires:
                proj.build_requires = setup_requires

            ext_modules = kwargs.get("ext_modules")
            if ext_modules is not None:
                proj.has_c_extensions = True

            package_dir = kwargs.get("package_dir")
            if isinstance(package_dir, ast.Dict):
                for key_node, val_node in zip(package_dir.keys, package_dir.values):
                    if isinstance(key_node, ast.Constant) and key_node.value == "":
                        proj.package_dir = _ast_str(val_node)

            scripts_node = kwargs.get("entry_points")
            if isinstance(scripts_node, ast.Dict):
                for key_node, val_node in zip(scripts_node.keys, scripts_node.values):
                    if isinstance(key_node, ast.Constant):
                        key_str = str(key_node.value)
                        if key_str == "console_scripts":
                            proj.scripts = _parse_entry_point_list(
                                _ast_str_list(val_node)
                            )
                        else:
                            proj.entry_points[key_str] = _parse_entry_point_list(
                                _ast_str_list(val_node)
                            )

            break

        return proj

    def detect_build_system(self, pyproject_data: PyProjectData) -> str:
        """Map build-backend to a human-readable build system name."""
        backend = pyproject_data.build_backend
        if not backend:
            if pyproject_data.build_requires:
                for req in pyproject_data.build_requires:
                    if "setuptools" in req:
                        return "setuptools"
                    if "poetry" in req:
                        return "poetry"
                    if "flit" in req:
                        return "flit"
                    if "hatch" in req:
                        return "hatch"
                    if "maturin" in req:
                        return "maturin"
            return "setuptools"
        return BUILD_BACKEND_MAP.get(backend, "unknown")

    def detect_c_extensions(
        self, pyproject_data: PyProjectData, file_list: list[str] | None = None
    ) -> bool:
        """Detect whether the project contains C/C++/Cython extension files."""
        if pyproject_data.has_c_extensions:
            return True

        backend = pyproject_data.build_backend
        if backend in ("maturin", "scikit_build_core.build"):
            return True

        for req in pyproject_data.build_requires:
            if any(ext_tool in req for ext_tool in ("cython", "maturin", "scikit-build")):
                return True

        for dep in pyproject_data.dependencies:
            if "cffi" in dep:
                return True

        if file_list:
            for f in file_list:
                if C_EXTENSION_PATTERNS.search(f):
                    return True

        return False

    def merge_configs(
        self,
        pyproject: PyProjectData | None,
        setup_cfg: PyProjectData | None,
        setup_py: PyProjectData | None,
    ) -> PyProjectData:
        """Merge configuration from multiple sources; pyproject.toml takes priority."""
        merged = PyProjectData()
        for source in (setup_py, setup_cfg, pyproject):
            if source is None:
                continue
            if source.name:
                merged.name = source.name
            if source.version:
                merged.version = source.version
            if source.requires_python:
                merged.requires_python = source.requires_python
            if source.build_backend:
                merged.build_backend = source.build_backend
            if source.build_requires:
                merged.build_requires = source.build_requires
            if source.dependencies:
                merged.dependencies = source.dependencies
            if source.optional_dependencies:
                merged.optional_dependencies = source.optional_dependencies
            if source.scripts:
                merged.scripts = source.scripts
            if source.entry_points:
                merged.entry_points = source.entry_points
            if source.classifiers:
                merged.classifiers = source.classifiers
            if source.project_urls:
                merged.project_urls = source.project_urls
            if source.has_c_extensions:
                merged.has_c_extensions = True
            if source.package_dir:
                merged.package_dir = source.package_dir
        return merged


def _parse_multiline(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_mapping(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _parse_entry_point_list(entries: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in entries:
        if "=" in entry:
            name, _, target = entry.partition("=")
            result[name.strip()] = target.strip()
    return result


def _ast_str(node: ast.expr | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _ast_str_list(node: ast.expr | None) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [
            elt.value
            for elt in node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    return []
