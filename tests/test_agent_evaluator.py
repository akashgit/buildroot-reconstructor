"""Tests for agent evaluator — L1-L4 scoring logic with mocked SSH."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from buildroot.agent.evaluator import Evaluator, _extract_error_lines
from buildroot.agent.models import EvalResult, TestResult


VALID_CONTAINERFILE = """\
FROM docker.io/library/maven:3.9-eclipse-temurin-17
WORKDIR /build
RUN echo hello
"""

INVALID_CONTAINERFILE = "INVALID not a containerfile @@@ {"


class TestL1Parse:
    def test_valid_containerfile_passes_l1(self):
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l1_parse(VALID_CONTAINERFILE, result) is True
        assert result.l1_parse is True

    def test_invalid_containerfile_still_parsed(self):
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        evaluator._l1_parse(INVALID_CONTAINERFILE, result)


class TestExtractErrorLines:
    def test_extracts_error_lines(self):
        log = (
            "Step 1: OK\n"
            "[ERROR] Failed to compile\n"
            "  at SomeClass.java:42\n"
            "Step 2: OK\n"
            "fatal: repo not found\n"
        )
        result = _extract_error_lines(log)
        assert "[ERROR]" in result or "fatal:" in result

    def test_fallback_to_tail_when_no_errors(self):
        log = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        result = _extract_error_lines(log, max_lines=3)
        assert result

    def test_deduplicates_lines(self):
        log = "[ERROR] same error\n[ERROR] same error\n[ERROR] same error\n"
        result = _extract_error_lines(log)
        assert result.count("[ERROR] same error") == 1

    def test_empty_log(self):
        result = _extract_error_lines("")
        assert result == ""


class TestEvaluatorWithMocks:
    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l2_build_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="STEP 1: FROM maven\nCOMMIT", stderr=""
        )
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l2_build(VALID_CONTAINERFILE, "test-tag", result) is True
        assert result.l2_build is True

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l2_build_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: could not build"
        )
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l2_build(VALID_CONTAINERFILE, "test-tag", result) is False
        assert result.error_summary

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l3_command_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="target/foo-1.0.jar\nBUILD_SUCCESS",
            stderr="",
        )
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l3_command("test-tag", result) is True
        assert result.l3_command is True

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l3_command_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="BUILD_FAILED",
            stderr="",
        )
        evaluator = Evaluator()
        result = EvalResult()
        assert evaluator._l3_command("test-tag", result) is False


class TestTrustCheck:
    def _check(self, containerfile: str, trusted: bool = True) -> EvalResult:
        evaluator = Evaluator()
        result = EvalResult()
        evaluator._l1_parse(containerfile, result)
        if trusted:
            evaluator._l1_5_trust(containerfile, result)
        return result

    def test_adoptium_passes(self):
        r = self._check("FROM docker.io/eclipse-temurin:17-jdk\nRUN echo hello")
        assert r.trust_violations == []

    def test_adoptium_unqualified_passes(self):
        r = self._check("FROM eclipse-temurin:17-jdk\nRUN echo hello")
        assert r.trust_violations == []

    def test_redhat_ubi_passes(self):
        r = self._check(
            "FROM registry.access.redhat.com/ubi9/openjdk-17\nRUN echo hello"
        )
        assert r.trust_violations == []

    def test_corretto_fails(self):
        r = self._check("FROM amazoncorretto:17\nRUN echo hello")
        assert len(r.trust_violations) == 1
        assert "amazoncorretto" in r.trust_violations[0]

    def test_openjdk_archive_fails(self):
        r = self._check("FROM openjdk:17-jdk\nRUN echo hello")
        assert len(r.trust_violations) >= 1

    def test_multistage_all_checked(self):
        cf = (
            "FROM eclipse-temurin:17-jdk AS builder\n"
            "RUN echo build\n"
            "FROM amazoncorretto:17\n"
            "COPY --from=builder /app /app\n"
        )
        r = self._check(cf)
        assert len(r.trust_violations) == 1
        assert "amazoncorretto" in r.trust_violations[0]

    def test_multistage_all_trusted_passes(self):
        cf = (
            "FROM eclipse-temurin:17-jdk AS builder\n"
            "RUN echo build\n"
            "FROM registry.access.redhat.com/ubi9/openjdk-17\n"
            "COPY --from=builder /app /app\n"
        )
        r = self._check(cf)
        assert r.trust_violations == []

    def test_untrusted_flag_false_skips(self):
        r = self._check("FROM amazoncorretto:17\nRUN echo hello", trusted=False)
        assert r.trust_violations == []

    def test_docker_io_library_prefix_normalized(self):
        r = self._check(
            "FROM docker.io/library/eclipse-temurin:17-jdk\nRUN echo hello"
        )
        assert r.trust_violations == []

    def test_arg_substitution_not_resolved(self):
        cf = "ARG BASE=eclipse-temurin:17-jdk\nFROM ${BASE}\nRUN echo hello"
        r = self._check(cf)
        assert len(r.trust_violations) >= 1

    def test_unresolved_arg_flagged(self):
        cf = "ARG VER\nFROM eclipse-temurin:${VER}\nRUN echo hello"
        r = self._check(cf)
        assert len(r.trust_violations) >= 1

    def test_short_arg_name_no_false_positive(self):
        cf = "ARG e\nFROM eclipse-temurin:17-jdk\nRUN echo hello"
        r = self._check(cf)
        assert r.trust_violations == []

    def test_scratch_allowed(self):
        cf = (
            "FROM eclipse-temurin:17-jdk AS builder\n"
            "RUN echo build\n"
            "FROM scratch\n"
            "COPY --from=builder /app /app\n"
        )
        r = self._check(cf)
        assert r.trust_violations == []


class TestL4FallbackPath:
    def test_fallback_when_jar_unavailable(self):
        evaluator = Evaluator()
        result = EvalResult(l3_command=True)
        with patch.object(evaluator, "_download_original_jar", return_value=None), \
             patch.object(evaluator, "l4_fallback_signals", return_value={
                 "bytecode_version_match": True,
                 "manifest_sanity": True,
             }):
            evaluator._l4_match("test-tag", "org.example:test:1.0", result)
        assert result.l4_score > 0
        assert result.l4_signal_source == "fallback_signals"
        assert result.bytecode_version_match is True
        assert result.manifest_sanity is True
        assert "L4 (approximate)" in result.error_summary

    def test_fallback_with_test_result(self):
        evaluator = Evaluator()
        result = EvalResult(l3_command=True)
        result.test_result = TestResult(available=True, passed=True, run=10, tests_passed=10)
        with patch.object(evaluator, "_download_original_jar", return_value=None), \
             patch.object(evaluator, "l4_fallback_signals", return_value={
                 "bytecode_version_match": True,
                 "manifest_sanity": True,
             }):
            evaluator._l4_match("test-tag", "org.example:test:1.0", result)
        assert result.unit_tests_pass is True
        score_with_tests = result.l4_score

        result2 = EvalResult(l3_command=True)
        with patch.object(evaluator, "_download_original_jar", return_value=None), \
             patch.object(evaluator, "l4_fallback_signals", return_value={
                 "bytecode_version_match": True,
                 "manifest_sanity": True,
             }):
            evaluator._l4_match("test-tag", "org.example:test:1.0", result2)
        assert result2.unit_tests_pass is None
        assert score_with_tests >= result2.l4_score

    def test_fallback_partial_signals(self):
        evaluator = Evaluator()
        result = EvalResult(l3_command=True)
        with patch.object(evaluator, "_download_original_jar", return_value=None), \
             patch.object(evaluator, "l4_fallback_signals", return_value={
                 "manifest_sanity": True,
             }):
            evaluator._l4_match("test-tag", "org.example:test:1.0", result)
        assert result.l4_score > 0
        assert result.bytecode_version_match is None
        assert result.manifest_sanity is True
        assert result.l4_signal_source == "fallback_signals"

    def test_normal_l4_path_unchanged(self):
        evaluator = Evaluator()
        result = EvalResult(l3_command=True)

        mock_report = MagicMock()
        mock_report.verdict = "EQUIVALENT"
        mock_report.equivalence_score.return_value = 0.95
        mock_report.structural.match = True
        mock_report.metadata.match = True
        mock_report.bytecode.match = False
        mock_report.bytecode.classes_divergent = ["Foo.class"]

        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            jar_path = Path(tmpdir) / "original.jar"
            jar_path.write_bytes(b"fake jar")
            rebuilt_path = Path(tmpdir) / "rebuilt.jar"
            rebuilt_path.write_bytes(b"fake rebuilt")

            with patch.object(evaluator, "_download_original_jar", return_value=jar_path), \
                 patch.object(evaluator, "_extract_rebuilt_jar", return_value=rebuilt_path), \
                 patch("buildroot.agent.evaluator.compare_jars", return_value=mock_report):
                evaluator._l4_match("test-tag", "org.example:test:1.0", result)

        assert result.l4_score == 0.95
        assert result.l4_signal_source == "full_comparison"
        assert result.comparison_verdict == "EQUIVALENT"

    def test_fallback_computes_reward_above_050(self):
        evaluator = Evaluator()
        result = EvalResult(l1_parse=True, l2_build=True, l3_command=True)
        result.test_result = TestResult(available=True, passed=True)
        with patch.object(evaluator, "_download_original_jar", return_value=None), \
             patch.object(evaluator, "l4_fallback_signals", return_value={
                 "bytecode_version_match": True,
                 "manifest_sanity": True,
                 "structural_match": 0.8,
             }):
            evaluator._l4_match("test-tag", "org.example:test:1.0", result)
        result.compute_reward()
        assert result.reward > 0.50

    def test_to_dict_includes_fallback_signals(self):
        result = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.7, reward=0.85, level_reached=3,
            l4_signal_source="fallback_signals",
            bytecode_version_match=True,
            manifest_sanity=True,
            unit_tests_pass=False,
            structural_match=0.6,
        )
        d = result.to_dict()
        assert d["l4_signal_source"] == "fallback_signals"
        assert "fallback_signals" in d
        assert d["fallback_signals"]["bytecode_version_match"] is True
        assert d["fallback_signals"]["structural_match"] == 0.6

    def test_to_dict_full_comparison_no_fallback(self):
        result = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.95, reward=0.97, level_reached=3,
            l4_signal_source="full_comparison",
        )
        d = result.to_dict()
        assert d["l4_signal_source"] == "full_comparison"
        assert "fallback_signals" not in d


class TestSelfBuiltReferencePath:
    def test_l4_self_built_reference_path(self):
        evaluator = Evaluator()
        result = EvalResult(l3_command=True)

        mock_report = MagicMock()
        mock_report.verdict = "EQUIVALENT"
        mock_report.equivalence_score.return_value = 0.85

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            jar_path = Path(tmpdir) / "self_built.jar"
            jar_path.write_bytes(b"fake self-built jar")
            rebuilt_path = Path(tmpdir) / "rebuilt.jar"
            rebuilt_path.write_bytes(b"fake rebuilt jar")

            with patch.object(evaluator, "_download_original_jar", return_value=None), \
                 patch("buildroot.eval.self_reference.build_reference_jar", return_value=jar_path), \
                 patch.object(evaluator, "_extract_rebuilt_jar", return_value=rebuilt_path), \
                 patch("buildroot.agent.evaluator.compare_jars", return_value=mock_report):
                evaluator._l4_match("test-tag", "org.example:test:1.0", result)

        assert result.l4_signal_source == "self_built_reference"
        assert result.l4_score == 0.85
        assert result.comparison_verdict == "EQUIVALENT"

    def test_l4_self_built_failure_falls_to_l4prime(self):
        evaluator = Evaluator()
        result = EvalResult(l3_command=True)
        with patch.object(evaluator, "_download_original_jar", return_value=None), \
             patch("buildroot.eval.self_reference.build_reference_jar", return_value=None), \
             patch.object(evaluator, "l4_fallback_signals", return_value={
                 "bytecode_version_match": True,
                 "manifest_sanity": True,
             }):
            evaluator._l4_match("test-tag", "org.example:test:1.0", result)
        assert result.l4_signal_source == "fallback_signals"
        assert result.l4_score > 0

    def test_l4_fallback_signals_includes_new_signals(self):
        evaluator = Evaluator()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            jar_path = tmp / "rebuilt.jar"
            jar_path.write_bytes(b"PK\x03\x04fake jar")
            source_root = tmp / "source"
            source_root.mkdir()
            pom = source_root / "pom.xml"
            pom.write_text("<project/>")

            mock_api = MagicMock(return_value=0.8)
            mock_dep = MagicMock(return_value=0.7)
            mock_res = MagicMock(return_value=0.9)

            with patch.object(evaluator, "_create_container", return_value="fake-cid"), \
                 patch.object(evaluator, "_extract_rebuilt_jar", return_value=jar_path), \
                 patch.object(evaluator, "_extract_source_root", return_value=source_root), \
                 patch.object(evaluator, "_remove_container"), \
                 patch("buildroot.agent.scorer.check_bytecode_version_match", return_value=True), \
                 patch("buildroot.agent.scorer.check_manifest_sanity", return_value=True), \
                 patch("buildroot.agent.scorer.check_structural_match", return_value=0.75), \
                 patch("buildroot.agent.scorer.compute_api_surface_match", mock_api), \
                 patch("buildroot.agent.scorer.compute_dependency_match", mock_dep), \
                 patch("buildroot.agent.scorer.compute_resource_completeness", mock_res):
                signals = evaluator.l4_fallback_signals("tag", "org.example:test:1.0", jdk_version="17")

            mock_api.assert_called_once()
            mock_dep.assert_called_once()
            mock_res.assert_called_once()
            assert signals["api_surface_match"] == 0.8
            assert signals["dependency_graph_match"] == 0.7
            assert signals["resource_completeness"] == 0.9


class TestPodmanCreateCpPattern:
    """Tests for the podman create + podman cp extraction pattern."""

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_create_container_returns_id(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="abc123def456\n", stderr=""
        )
        evaluator = Evaluator()
        cid = evaluator._create_container("test-tag")
        assert cid == "abc123def456"
        call_args = mock_run.call_args[0][0]
        assert call_args[-3:] == ["create", "test-tag", "true"]

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_create_container_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        evaluator = Evaluator()
        assert evaluator._create_container("test-tag") is None

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_remove_container(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        evaluator = Evaluator()
        evaluator._remove_container("abc123")
        call_args = mock_run.call_args[0][0]
        assert call_args[-2:] == ["rm", "abc123"]

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_extract_rebuilt_jar_uses_in_container_find(self, mock_run):
        evaluator = Evaluator()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)
            local_jar = dest / "test-1.0-rebuilt.jar"

            def side_effect(cmd, **kwargs):
                if isinstance(cmd, list) and "start" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "exec" in cmd:
                    return MagicMock(returncode=0, stdout="./target/test-1.0.jar\n", stderr="")
                if isinstance(cmd, list) and "stop" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "cp" in cmd:
                    if "/output/rebuilt.jar" in str(cmd):
                        return MagicMock(returncode=1, stdout="", stderr="")
                    local_jar.write_bytes(b"x" * 2048)
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=1, stdout="", stderr="")

            mock_run.side_effect = side_effect
            result = evaluator._extract_jar_from_container(
                "container-id", "test", "1.0", dest,
            )
            assert result == local_jar
            exec_calls = [c for c in mock_run.call_args_list
                         if isinstance(c[0][0], list) and "exec" in c[0][0]]
            assert len(exec_calls) == 1
            exec_cmd = " ".join(exec_calls[0][0][0])
            assert "find . -maxdepth 5" in exec_cmd

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_extract_rebuilt_jar_creates_own_container_when_none_given(self, mock_run):
        call_count = [0]

        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if isinstance(cmd, list) and "create" in cmd:
                return MagicMock(returncode=0, stdout="cid123\n", stderr="")
            if isinstance(cmd, list) and "cp" in cmd and "/output/rebuilt.jar" in str(cmd):
                return MagicMock(returncode=1, stdout="", stderr="")
            if isinstance(cmd, list) and "start" in cmd:
                return MagicMock(returncode=0)
            if isinstance(cmd, list) and "exec" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            if isinstance(cmd, list) and "stop" in cmd:
                return MagicMock(returncode=0)
            if isinstance(cmd, list) and "rm" in cmd:
                return MagicMock(returncode=0)
            return MagicMock(returncode=1, stdout="", stderr="")

        mock_run.side_effect = side_effect
        evaluator = Evaluator()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = evaluator._extract_rebuilt_jar("tag", "art", "1.0", Path(tmpdir))
        first_call_args = mock_run.call_args_list[0][0][0]
        assert first_call_args[-3:] == ["create", "tag", "true"]
        last_call_args = mock_run.call_args_list[-1][0][0]
        assert last_call_args[-2:] == ["rm", "cid123"]

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_fallback_signals_creates_one_container(self, mock_run):
        """l4_fallback_signals creates one container and reuses it."""
        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and "create" in cmd:
                return MagicMock(returncode=0, stdout="shared-cid\n", stderr="")
            if isinstance(cmd, list) and "cp" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="")
            if isinstance(cmd, list) and "start" in cmd:
                return MagicMock(returncode=0)
            if isinstance(cmd, list) and "exec" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            if isinstance(cmd, list) and "stop" in cmd:
                return MagicMock(returncode=0)
            if isinstance(cmd, list) and "rm" in cmd:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        evaluator = Evaluator()
        signals = evaluator.l4_fallback_signals("tag", "org.example:test:1.0")
        create_calls = [c for c in mock_run.call_args_list if "create" in str(c)]
        assert len(create_calls) == 1
        rm_calls = [c for c in mock_run.call_args_list if "\"rm\"" in str(c) or "'rm'" in str(c)]
        assert len(rm_calls) == 1

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_extract_source_uses_find_and_podman_cp(self, mock_run):
        """_extract_source_from_container uses find then podman cp."""
        evaluator = Evaluator()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "source"
            dest.mkdir()

            def side_effect(cmd, **kwargs):
                if isinstance(cmd, list) and "start" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "exec" in cmd:
                    return MagicMock(returncode=0, stdout="/build/src/main/java\n", stderr="")
                if isinstance(cmd, list) and "stop" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "cp" in cmd:
                    java_file = dest / "main" / "java" / "com" / "Test.java"
                    java_file.parent.mkdir(parents=True, exist_ok=True)
                    java_file.write_text("class Test {}")
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect
            result = evaluator._extract_source_from_container("cid", dest)
            assert result == dest
            podman_run_calls = [c for c in mock_run.call_args_list
                               if isinstance(c.args[0], list) and len(c.args[0]) > 1 and c.args[0][1] == "run"]
            assert len(podman_run_calls) == 0


class TestBroadenedJarDiscovery:
    """Verify the broadened find pattern discovers deep JARs and excludes caches."""

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_deep_submodule_jar_found(self, mock_run):
        """A JAR at lib/submodule/target/foo.jar is found by the broader find."""
        evaluator = Evaluator()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)
            local_jar = dest / "foo-1.0-rebuilt.jar"

            def side_effect(cmd, **kwargs):
                if isinstance(cmd, list) and "cp" in cmd and "/output/rebuilt.jar" in str(cmd):
                    return MagicMock(returncode=1, stdout="", stderr="")
                if isinstance(cmd, list) and "start" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "exec" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout="./lib/submodule/target/foo-1.0.jar\n",
                        stderr="",
                    )
                if isinstance(cmd, list) and "stop" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "cp" in cmd:
                    local_jar.write_bytes(b"x" * 2048)
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=1, stdout="", stderr="")

            mock_run.side_effect = side_effect
            result = evaluator._extract_jar_from_container(
                "cid", "foo", "1.0", dest,
            )
            assert result is not None
            assert result == local_jar

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l3_find_command_excludes_m2(self, mock_run):
        """.m2 cache JARs are excluded from the L3 find command."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="BUILD_SUCCESS", stderr=""
        )
        evaluator = Evaluator()
        result = EvalResult()
        evaluator._l3_command("test-tag", result)
        shell_cmd = mock_run.call_args[0][0]
        sh_script = shell_cmd[-1]
        assert "-not -path './.m2/*'" in sh_script

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l3_find_command_excludes_webinf_lib(self, mock_run):
        """WEB-INF/lib JARs are excluded from the L3 find command."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="BUILD_SUCCESS", stderr=""
        )
        evaluator = Evaluator()
        result = EvalResult()
        evaluator._l3_command("test-tag", result)
        shell_cmd = mock_run.call_args[0][0]
        sh_script = shell_cmd[-1]
        assert "-not -path '*/WEB-INF/lib/*'" in sh_script

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l4_find_excludes_m2_and_webinf(self, mock_run):
        """.m2 and WEB-INF/lib are excluded in the L4 in-container find."""
        evaluator = Evaluator()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)

            def side_effect(cmd, **kwargs):
                if isinstance(cmd, list) and "cp" in cmd and "/output/rebuilt.jar" in str(cmd):
                    return MagicMock(returncode=1, stdout="", stderr="")
                if isinstance(cmd, list) and "start" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "exec" in cmd:
                    find_script = cmd[-1]
                    assert "-not -path './.m2/*'" in find_script
                    assert "-not -path '*/WEB-INF/lib/*'" in find_script
                    return MagicMock(returncode=0, stdout="", stderr="")
                if isinstance(cmd, list) and "stop" in cmd:
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1, stdout="", stderr="")

            mock_run.side_effect = side_effect
            evaluator._extract_jar_from_container("cid", "art", "1.0", dest)

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l4_find_excludes_gradle_cache(self, mock_run):
        """.gradle cache JARs are excluded in the L4 in-container find."""
        evaluator = Evaluator()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)

            def side_effect(cmd, **kwargs):
                if isinstance(cmd, list) and "cp" in cmd and "/output/rebuilt.jar" in str(cmd):
                    return MagicMock(returncode=1, stdout="", stderr="")
                if isinstance(cmd, list) and "start" in cmd:
                    return MagicMock(returncode=0)
                if isinstance(cmd, list) and "exec" in cmd:
                    find_script = cmd[-1]
                    assert "-not -path '*/.gradle/*'" in find_script
                    return MagicMock(returncode=0, stdout="", stderr="")
                if isinstance(cmd, list) and "stop" in cmd:
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1, stdout="", stderr="")

            mock_run.side_effect = side_effect
            evaluator._extract_jar_from_container("cid", "art", "1.0", dest)
