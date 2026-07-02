"""Python version inference with priority heuristic."""

from __future__ import annotations

import logging
import re

from buildroot.pipeline.models import CIData, Confidence, Source
from buildroot.pipeline.models_python import PyProjectData, PythonSpec

logger = logging.getLogger(__name__)

DEFAULT_PYTHON_VERSION = "3.11"

CLASSIFIER_VERSION_RE = re.compile(
    r"Programming Language :: Python :: (3\.\d+)$"
)

SETUP_PYTHON_RE = re.compile(r"setup-python.*?python-version[:\s]+['\"]?(\d+\.\d+)")

PEP_440_GTE_RE = re.compile(r">=\s*(\d+\.\d+)")
PEP_440_LT_RE = re.compile(r"<\s*(\d+(?:\.\d+)?)")
PEP_440_EQ_RE = re.compile(r"==\s*(\d+\.\d+)")
PEP_440_COMPAT_RE = re.compile(r"~=\s*(\d+\.\d+)")

MIN_SUPPORTED_PYTHON = "3.8"
SUPPORTED_PYTHON_VERSIONS = ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"]


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse '3.11' into (3, 11) for comparison."""
    return tuple(int(x) for x in version.split("."))


def _clamp_python_version(version: str) -> str:
    """Clamp a Python version to at least MIN_SUPPORTED_PYTHON.

    Versions below MIN_SUPPORTED_PYTHON are replaced with the default
    (3.11) because their Docker images rely on EOL Debian releases whose
    apt repos return 404.
    """
    if _version_tuple(version) < _version_tuple(MIN_SUPPORTED_PYTHON):
        return DEFAULT_PYTHON_VERSION
    return version


def _pick_best_python_version(min_version: str, upper_bound: str) -> str:
    """Pick the highest supported Python version in [min_version, upper_bound).

    The lower bound is clamped to at least MIN_SUPPORTED_PYTHON.
    Falls back to DEFAULT_PYTHON_VERSION if no supported version satisfies.
    """
    min_t = max(_version_tuple(min_version), _version_tuple(MIN_SUPPORTED_PYTHON))
    upper_t = _version_tuple(upper_bound)

    best = ""
    for v in SUPPORTED_PYTHON_VERSIONS:
        v_t = _version_tuple(v)
        if min_t <= v_t < upper_t:
            best = v

    return best or DEFAULT_PYTHON_VERSION


class PythonVersionResolver:
    """Resolve Python version from multiple sources using a priority heuristic."""

    def resolve(
        self,
        pyproject_data: PyProjectData,
        ci_data: CIData | None = None,
        *,
        python_version_file: str = "",
        tool_versions_file: str = "",
        tox_ini_content: str = "",
    ) -> PythonSpec:
        spec = PythonSpec()
        all_signals: list[dict[str, str]] = []

        # P0: python_requires in pyproject.toml
        p0_version = self._check_requires_python(pyproject_data.requires_python)
        if p0_version:
            all_signals.append({
                "source": "requires-python",
                "version": p0_version,
                "priority": "0",
            })
            if not spec.version:
                spec.version = p0_version
                spec.confidence = Confidence(
                    level=Source.OBSERVED,
                    reason="Python version from requires-python in pyproject.toml",
                )
                spec.source_description = "pyproject.toml requires-python"

        # P1: .python-version file
        p1_version = self._check_python_version_file(python_version_file)
        if p1_version:
            all_signals.append({
                "source": ".python-version",
                "version": p1_version,
                "priority": "1",
            })
            if not spec.version:
                spec.version = p1_version
                spec.confidence = Confidence(
                    level=Source.OBSERVED,
                    reason="Python version from .python-version file",
                )
                spec.source_description = ".python-version file"

        # P2: CI setup-python action
        p2_version = self._check_ci_setup_python(ci_data)
        if p2_version:
            all_signals.append({
                "source": "CI setup-python",
                "version": p2_version,
                "priority": "2",
            })
            if not spec.version:
                spec.version = p2_version
                spec.confidence = Confidence(
                    level=Source.OBSERVED,
                    reason="Python version from CI setup-python action",
                )
                spec.source_description = "CI setup-python action"

        # P3: tox.ini basepython
        p3_version = self._check_tox_basepython(tox_ini_content)
        if p3_version:
            all_signals.append({
                "source": "tox.ini basepython",
                "version": p3_version,
                "priority": "3",
            })
            if not spec.version:
                spec.version = p3_version
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="Python version from tox.ini basepython",
                )
                spec.source_description = "tox.ini basepython"

        # P4: .tool-versions
        p4_version = self._check_tool_versions(tool_versions_file)
        if p4_version:
            all_signals.append({
                "source": ".tool-versions",
                "version": p4_version,
                "priority": "4",
            })
            if not spec.version:
                spec.version = p4_version
                spec.confidence = Confidence(
                    level=Source.OBSERVED,
                    reason="Python version from .tool-versions file",
                )
                spec.source_description = ".tool-versions file"

        # P5: Classifier strings
        p5_version = self._check_classifiers(pyproject_data.classifiers)
        if p5_version:
            all_signals.append({
                "source": "classifier",
                "version": p5_version,
                "priority": "5",
            })
            if not spec.version:
                spec.version = p5_version
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="Python version from classifier strings",
                )
                spec.source_description = "Classifier 'Programming Language :: Python :: 3.X'"

        # P6: Default
        if not spec.version:
            spec.version = DEFAULT_PYTHON_VERSION
            spec.confidence = Confidence(
                level=Source.DEFAULTED,
                reason=f"No Python version signal found; defaulting to {DEFAULT_PYTHON_VERSION}",
            )
            spec.source_description = "Default (no signal found)"

        spec.needs_build_tools = pyproject_data.has_c_extensions
        spec.base_image = self._map_version_to_image(
            spec.version, pyproject_data.has_c_extensions
        )
        spec.conflicts = self._detect_conflicts(all_signals)

        return spec

    def _check_requires_python(self, requires_python: str) -> str:
        if not requires_python:
            return ""

        m = PEP_440_EQ_RE.search(requires_python)
        if m:
            return _clamp_python_version(m.group(1))

        m = PEP_440_COMPAT_RE.search(requires_python)
        if m:
            return _clamp_python_version(m.group(1))

        m = PEP_440_GTE_RE.search(requires_python)
        if m:
            min_ver = m.group(1)
            upper_m = PEP_440_LT_RE.search(requires_python)
            if upper_m:
                return _pick_best_python_version(min_ver, upper_m.group(1))
            return _clamp_python_version(min_ver)

        bare = re.match(r"^(\d+\.\d+)$", requires_python.strip())
        if bare:
            return _clamp_python_version(bare.group(1))

        return ""

    def _check_python_version_file(self, content: str) -> str:
        if not content:
            return ""
        line = content.strip().splitlines()[0].strip()
        m = re.match(r"^(\d+\.\d+)", line)
        return m.group(1) if m else ""

    def _check_ci_setup_python(self, ci_data: CIData | None) -> str:
        if not ci_data:
            return ""
        py_version = ci_data.env_vars.get("_buildroot_python_version")
        if py_version:
            m = re.match(r"^(\d+\.\d+)", py_version.strip())
            return m.group(1) if m else ""
        for cmd in ci_data.build_commands:
            m = SETUP_PYTHON_RE.search(cmd)
            if m:
                return m.group(1)
        return ""

    def _check_tox_basepython(self, tox_content: str) -> str:
        if not tox_content:
            return ""
        for line in tox_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("basepython"):
                m = re.search(r"python(\d+\.\d+)", stripped)
                if m:
                    return m.group(1)
                m = re.search(r"(\d+\.\d+)", stripped)
                if m:
                    return m.group(1)
        return ""

    def _check_tool_versions(self, content: str) -> str:
        if not content:
            return ""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("python"):
                m = re.search(r"(\d+\.\d+)", stripped)
                if m:
                    return m.group(1)
        return ""

    def _check_classifiers(self, classifiers: list[str]) -> str:
        versions: list[str] = []
        for c in classifiers:
            m = CLASSIFIER_VERSION_RE.match(c)
            if m:
                versions.append(m.group(1))
        if not versions:
            return ""
        versions.sort(key=lambda v: tuple(int(x) for x in v.split(".")))
        return versions[-1]

    @staticmethod
    def _map_version_to_image(version: str, has_c_extensions: bool) -> str:
        # Safety net: ensure the image version is at least MIN_SUPPORTED_PYTHON
        if _version_tuple(version) < _version_tuple(MIN_SUPPORTED_PYTHON):
            version = DEFAULT_PYTHON_VERSION
        if has_c_extensions:
            return f"docker.io/library/python:{version}-bookworm"
        return f"docker.io/library/python:{version}-slim"

    def _detect_conflicts(self, signals: list[dict[str, str]]) -> list[dict[str, str]]:
        versions: dict[str, list[str]] = {}
        for sig in signals:
            v = sig.get("version", "")
            if v:
                versions.setdefault(v, []).append(sig["source"])

        if len(versions) <= 1:
            return []

        conflicts = []
        for version, sources in versions.items():
            conflicts.append({
                "version": version,
                "sources": ", ".join(sources),
            })
        return conflicts
