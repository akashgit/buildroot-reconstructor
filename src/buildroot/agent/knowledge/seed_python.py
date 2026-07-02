"""Seed the knowledge base with Python packaging entries."""

from __future__ import annotations

from pathlib import Path

import structlog

from buildroot.agent.knowledge.schema import TipEntry, TrickEntry, save_entry

logger = structlog.get_logger()


def seed_python_entries(kb_dir: Path) -> int:
    """Seed the knowledge base with Python-specific entries.

    Returns the number of entries created.
    """
    entries = [
        TipEntry(
            name="source-date-epoch-python",
            description="Set SOURCE_DATE_EPOCH=0 for reproducible Python sdist timestamps",
            tags=["reproducibility", "python", "timestamps"],
            build_systems=["setuptools", "flit", "hatch", "poetry"],
            trigger="Timestamps in sdist differ from original",
            solution="Set SOURCE_DATE_EPOCH=0 in the Containerfile before building",
            caveats="Only works with setuptools>=69, flit>=3.8, hatch>=1.17",
        ),
        TipEntry(
            name="python-build-pep517",
            description="Use PEP 517 build frontend for standard Python packages",
            tags=["build", "pep517", "python"],
            build_systems=["setuptools", "flit", "hatch"],
            trigger="Standard PEP 517 Python package build",
            solution="pip install build && python -m build --sdist --wheel",
            caveats="Requires the 'build' package, not setuptools directly",
        ),
        TrickEntry(
            name="setuptools-scm-version",
            description="Fix setuptools-scm version detection failures in shallow clones",
            tags=["setuptools-scm", "version", "git"],
            build_systems=["setuptools"],
            error_pattern=r"setuptools[_-]scm was unable to detect version|LookupError.*setuptools.scm",
            fix="Use full git clone (not --depth 1) or set SETUPTOOLS_SCM_PRETEND_VERSION={version}",
            example_log="setuptools-scm was unable to detect version for /build",
        ),
        TrickEntry(
            name="poetry-no-venv",
            description="Disable Poetry virtualenv creation inside containers",
            tags=["poetry", "virtualenv", "build"],
            build_systems=["poetry"],
            error_pattern=r"poetry.*virtualenv|poetry.*install",
            fix="Run 'poetry config virtualenvs.create false' before 'poetry build'",
            example_log="Creating virtualenv in /build/.venv ... failed",
        ),
        TipEntry(
            name="wheel-reproducibility",
            description="Ensure reproducible wheel builds with SOURCE_DATE_EPOCH and PYTHONHASHSEED",
            tags=["wheel", "reproducibility", "python"],
            build_systems=["setuptools", "flit", "hatch"],
            trigger="Wheel file differs from original",
            solution="Ensure SOURCE_DATE_EPOCH=0 is set. For setuptools, also set PYTHONHASHSEED=0",
            caveats="Wheel RECORD file contains hashes that will differ if any file differs",
        ),
        TrickEntry(
            name="missing-build-deps",
            description="Install system headers for C extension compilation",
            tags=["build", "dependencies", "c-extension"],
            build_systems=["setuptools", "maturin", "scikit-build"],
            error_pattern=r"fatal error:.*No such file|cannot find -l|gcc.*error",
            fix=(
                "Install system packages: apt-get install build-essential libffi-dev libssl-dev. "
                "Check pyproject.toml for build-requires hints."
            ),
            example_log="fatal error: Python.h: No such file or directory",
        ),
        TipEntry(
            name="git-tag-patterns-python",
            description="Common git tag patterns for Python package releases",
            tags=["git", "tags", "version"],
            build_systems=["setuptools", "poetry", "flit", "hatch"],
            trigger="Cannot find git tag for Python package version",
            solution=(
                "Try tag patterns: v{version}, {version}, {package}-{version}, "
                "release-{version}, release/{version}"
            ),
            caveats="Some projects use non-standard tag formats",
        ),
        TrickEntry(
            name="egg-info-ordering",
            description="Handle non-deterministic file ordering in .egg-info directories",
            tags=["egg-info", "reproducibility", "setuptools"],
            build_systems=["setuptools"],
            error_pattern=r"\.egg-info|PKG-INFO",
            fix="Exclude .egg-info directories from comparison -- they contain non-deterministic file ordering",
            example_log="structural mismatch in .egg-info/SOURCES.txt ordering",
        ),
    ]

    count = 0
    for entry in entries:
        try:
            save_entry(entry, kb_dir)
            count += 1
        except Exception as e:
            logger.warning("seed_entry_failed", name=entry.name, error=str(e))

    logger.info("python_kb_seeded", count=count)
    return count
