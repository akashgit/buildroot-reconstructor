"""Shared test fixtures for buildroot tests."""

import shutil
import tempfile
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def output_dir():
    """Create a temp directory for test output, cleaned up after the test."""
    d = tempfile.mkdtemp(prefix="buildroot-test-")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def podman_available():
    """Check if podman is available and running. Skip test if not."""
    if not shutil.which("podman"):
        pytest.skip("podman not found on PATH")
    import subprocess

    result = subprocess.run(
        ["podman", "info"], capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        pytest.skip("podman is not running (podman info failed)")
    return True
