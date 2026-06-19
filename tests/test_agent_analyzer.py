"""Tests for agent analyzer — dead-end registry and error pattern constants."""

from buildroot.agent.analyzer import (
    FUNDAMENTAL_BLOCKERS,
    all_exhausted,
    update_dead_ends,
)
from buildroot.agent.models import DeadEndEntry


class TestDeadEndRegistry:
    def test_update_creates_new_entry(self):
        dead_ends: list[DeadEndEntry] = []
        update_dead_ends(dead_ends, "test_error", "approach1", "log summary")
        assert len(dead_ends) == 1
        assert dead_ends[0].failure_count == 1

    def test_update_increments_existing(self):
        dead_ends: list[DeadEndEntry] = []
        update_dead_ends(dead_ends, "test_error", "approach1", "log1")
        update_dead_ends(dead_ends, "test_error", "approach1", "log2")
        assert len(dead_ends) == 1
        assert dead_ends[0].failure_count == 2

    def test_different_approaches_separate(self):
        dead_ends: list[DeadEndEntry] = []
        update_dead_ends(dead_ends, "test_error", "approach1", "log1")
        update_dead_ends(dead_ends, "test_error", "approach2", "log2")
        assert len(dead_ends) == 2

    def test_all_exhausted_false_when_empty(self):
        assert not all_exhausted([])

    def test_all_exhausted_false_when_some_remaining(self):
        de1 = DeadEndEntry(error_class="a", approach="x", failure_count=2, threshold=2)
        de2 = DeadEndEntry(error_class="b", approach="y", failure_count=1, threshold=2)
        assert not all_exhausted([de1, de2])

    def test_all_exhausted_true_when_all_done(self):
        de1 = DeadEndEntry(error_class="a", approach="x", failure_count=2, threshold=2)
        de2 = DeadEndEntry(error_class="b", approach="y", failure_count=3, threshold=2)
        assert all_exhausted([de1, de2])


class TestFundamentalBlockers:
    def test_credentials_is_blocker(self):
        assert "environment/credentials" in FUNDAMENTAL_BLOCKERS

    def test_clone_failed_is_blocker(self):
        assert "source/clone_failed" in FUNDAMENTAL_BLOCKERS
