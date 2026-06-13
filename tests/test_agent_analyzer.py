"""Tests for agent analyzer — error classification, dead-end registry, fix suggestions."""

import pytest

from buildroot.agent.analyzer import (
    FUNDAMENTAL_BLOCKERS,
    AnalysisResult,
    all_exhausted,
    analyze,
    classify_error,
    update_dead_ends,
)
from buildroot.agent.models import DeadEndEntry, EvalResult


class TestClassifyError:
    def test_dependency_resolution_missing(self):
        log = "[ERROR] Could not resolve artifact org.foo:bar:1.0"
        assert classify_error(log) == "dependency_resolution/missing_artifact"

    def test_dependency_resolution_find(self):
        log = "Could not find dependencies for project"
        assert classify_error(log) == "dependency_resolution/missing_artifact"

    def test_version_conflict(self):
        log = "Dependency convergence error for com.google.guava"
        assert classify_error(log) == "dependency_resolution/version_conflict"

    def test_jdk_mismatch_source(self):
        log = "error: source option 17 is not supported"
        assert classify_error(log) == "compilation/jdk_mismatch"

    def test_jdk_mismatch_target(self):
        log = "error: target release 11 is not supported"
        assert classify_error(log) == "compilation/jdk_mismatch"

    def test_jdk_mismatch_class_version(self):
        log = "class file has wrong version 61.0, should be 55.0"
        assert classify_error(log) == "compilation/jdk_mismatch"

    def test_syntax_error(self):
        log = "error: cannot find symbol"
        assert classify_error(log) == "compilation/syntax_error"

    def test_plugin_error(self):
        log = "Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin on project foo"
        assert classify_error(log) == "plugin/configuration_error"

    def test_gpg_error(self):
        log = 'Cannot run program "gpg": No such file'
        assert classify_error(log) == "plugin/gpg_error"

    def test_gha_secrets(self):
        log = "ARG TOKEN=${{ secrets.GITHUB_TOKEN }}"
        assert classify_error(log) == "environment/gha_secrets"

    def test_gha_expressions(self):
        log = "ENV FOO=${{ toJSON(github.event) }}"
        assert classify_error(log) == "environment/gha_expressions"

    def test_image_resolution(self):
        log = 'short-name "maven:3.9" did not resolve'
        assert classify_error(log) == "environment/image_resolution"

    def test_wrong_tag(self):
        log = "fatal: Remote branch v3.14.0 not found in upstream origin"
        assert classify_error(log) == "source/wrong_tag"

    def test_clone_failed(self):
        log = "fatal: repository 'https://github.com/foo/bar' not found"
        assert classify_error(log) == "source/clone_failed"

    def test_multi_module(self):
        log = "Could not find artifact org.foo:parent in reactor"
        assert classify_error(log) == "build_tool/multi_module"

    def test_maven_wrapper(self):
        log = "./mvnw: Permission denied"
        assert classify_error(log) == "build_tool/maven_wrapper"

    def test_oom(self):
        log = "java.lang.OutOfMemoryError: Java heap space"
        assert classify_error(log) == "resource/oom"

    def test_disk_space(self):
        log = "No space left on device"
        assert classify_error(log) == "resource/disk_space"

    def test_credentials(self):
        log = "401 Unauthorized"
        assert classify_error(log) == "environment/credentials"

    def test_unknown(self):
        log = "some completely unrecognized error"
        assert classify_error(log) == "unknown"

    def test_build_log_also_checked(self):
        result = classify_error("", "java.lang.OutOfMemoryError")
        assert result == "resource/oom"


class TestAnalyze:
    def test_returns_analysis_result(self):
        er = EvalResult(error_summary="Could not resolve artifact foo:bar:1.0")
        result = analyze(er, [])
        assert isinstance(result, AnalysisResult)
        assert result.error_class == "dependency_resolution/missing_artifact"
        assert not result.is_fundamental_blocker

    def test_fundamental_blocker_detected(self):
        er = EvalResult(error_summary="401 Unauthorized access to repo")
        result = analyze(er, [])
        assert result.is_fundamental_blocker

    def test_fix_suggestion_not_empty(self):
        er = EvalResult(error_summary="source option 17 is not supported")
        result = analyze(er, [])
        assert result.fix_suggestion


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
