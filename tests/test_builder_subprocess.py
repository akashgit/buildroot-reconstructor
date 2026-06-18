"""Tests for Builder agent — skipped (builder.py removed per issue #42).

The Builder class was removed from the default pipeline. These tests are
preserved as documentation of the old interface. The --legacy-builder flag
can restore Builder functionality if builder.py is re-added to the repo.
"""

import pytest


@pytest.mark.skip(reason="Builder removed per issue #42 — legacy tests preserved for reference")
class TestExtractContainerfile:
    pass


@pytest.mark.skip(reason="Builder removed per issue #42 — legacy tests preserved for reference")
class TestBuilderSubprocess:
    pass
