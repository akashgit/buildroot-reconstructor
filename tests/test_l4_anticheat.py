"""Tests for L4 anti-cheat pipeline — validate_containerfile, check_build_log, DB constraint."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from buildroot.agent.evaluator import Evaluator, validate_containerfile, check_build_log
from buildroot.agent.models import EvalResult


# ---------------------------------------------------------------------------
# validate_containerfile tests
# ---------------------------------------------------------------------------

class TestValidateContainerfileRejects:
    def test_rejects_jar_download_wget(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN wget https://repo1.maven.org/maven2/axis/axis/1.4/axis-1.4.jar -O target/axis-1.4.jar
"""
        passed, violations = validate_containerfile(cf, "axis:axis:1.4")
        assert passed is False
        assert any("JAR download" in v for v in violations)
        assert any("source acquisition" in v.lower() or "source" in v.lower() for v in violations)

    def test_rejects_manifest_stub(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN python3 -c "import zipfile; z = zipfile.ZipFile('target/out.jar', 'w'); z.close()"
"""
        passed, violations = validate_containerfile(cf, "org.example:stub:1.0")
        assert passed is False
        assert any("zipfile" in v.lower() for v in violations)

    def test_rejects_version_swap_fake(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN wget https://repo1.maven.org/maven2/axis/axis/1.3/axis-1.3.jar -O target/axis-1.3.jar
"""
        passed, violations = validate_containerfile(cf, "axis:axis:1.3")
        assert passed is False
        assert any("JAR download" in v for v in violations)

    def test_rejects_self_referential_download(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN wget https://repo1.maven.org/maven2/commons-httpclient/commons-httpclient/3.1/commons-httpclient-3.1.jar
"""
        passed, violations = validate_containerfile(cf, "commons-httpclient:commons-httpclient:3.1")
        assert passed is False

    def test_rejects_only_clone_no_compile(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN git clone https://github.com/apache/commons-io.git
"""
        passed, violations = validate_containerfile(cf, "org.apache.commons:commons-io:2.11.0")
        assert passed is False
        assert any("compilation" in v.lower() for v in violations)

    def test_rejects_only_mvn_no_source(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN mvn clean install -DskipTests
"""
        passed, violations = validate_containerfile(cf, "org.example:artifact:1.0")
        assert passed is False
        assert any("source acquisition" in v.lower() or "source" in v.lower() for v in violations)

    def test_rejects_echo_manifest(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN echo "Manifest-Version: 1.0" > META-INF/MANIFEST.MF
"""
        passed, violations = validate_containerfile(cf, "org.example:stub:1.0")
        assert passed is False
        assert any("MANIFEST" in v for v in violations)

    def test_rejects_base64_obfuscation(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN echo "aHR0cHM6Ly9yZXBvLm1hdmVuLm9yZw==" | base64 -d | xargs wget
"""
        passed, violations = validate_containerfile(cf, "org.example:lib:1.0")
        assert passed is False
        assert any("obfuscat" in v.lower() or "base64" in v.lower() for v in violations)

    def test_rejects_hidden_jar_after_sources_jar(self):
        cf = '''
FROM eclipse-temurin:17-jdk
RUN wget https://repo1.maven.org/maven2/org/example/lib-1.0-sources.jar && wget https://repo1.maven.org/maven2/org/example/lib-1.0.jar
RUN git clone https://github.com/example/project.git && mvn install
'''
        passed, violations = validate_containerfile(cf, 'org.example:lib:1.0')
        assert passed is False
        assert any('JAR download' in v for v in violations)

    def test_rejects_curl_jar(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN curl -o target/lib.jar https://repo1.maven.org/maven2/org/example/lib/1.0/lib-1.0.jar
"""
        passed, violations = validate_containerfile(cf, "org.example:lib:1.0")
        assert passed is False
        assert any("JAR download" in v for v in violations)


class TestValidateContainerfilePasses:
    def test_legitimate_build_passes(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN git clone https://github.com/apache/activemq.git src
RUN cd src && mvn clean install -DskipTests -pl activemq-client-jakarta
RUN cp src/activemq-client-jakarta/target/activemq-client-jakarta-5.18.3.jar /output/rebuilt.jar
"""
        passed, violations = validate_containerfile(cf, "org.apache.activemq:activemq-client-jakarta:5.18.3")
        assert passed is True
        assert violations == []

    def test_sources_jar_download_allowed(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN wget https://repo1.maven.org/maven2/org/example/lib/1.0/lib-1.0-sources.jar
RUN mvn clean install
"""
        passed, violations = validate_containerfile(cf, "org.example:lib:1.0")
        assert passed is True

    def test_maven_wrapper_jar_allowed(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN git clone https://github.com/example/project.git src
RUN cd src && wget https://repo1.maven.org/maven2/org/apache/maven/wrapper/maven-wrapper.jar
RUN cd src && ./mvnw clean install
"""
        passed, violations = validate_containerfile(cf, "org.example:project:1.0")
        assert passed is True

    def test_gradle_wrapper_allowed(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN git clone https://github.com/example/project.git src
RUN cd src && wget https://services.gradle.org/distributions/gradle-wrapper.jar
RUN cd src && ./gradlew build
"""
        passed, violations = validate_containerfile(cf, "org.example:project:1.0")
        assert passed is True

    def test_svn_checkout_with_ant(self):
        cf = """\
FROM eclipse-temurin:8-jdk
WORKDIR /build
RUN svn checkout https://svn.apache.org/repos/asf/commons/proper/lang src
RUN cd src && ant jar
"""
        passed, violations = validate_containerfile(cf, "commons-lang:commons-lang:2.6")
        assert passed is True

    def test_tarball_source_with_javac(self):
        cf = """\
FROM eclipse-temurin:11-jdk
WORKDIR /build
RUN wget https://github.com/example/project/archive/v1.0.tar.gz && tar xzf v1.0.tar.gz
RUN cd project-1.0 && javac -d out src/**/*.java
"""
        passed, violations = validate_containerfile(cf, "org.example:project:1.0")
        assert passed is True

    def test_cfr_tool_jar_allowed(self):
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN git clone https://github.com/example/project.git src
RUN wget https://github.com/leibnitz27/cfr/releases/download/0.152/cfr-0.152.jar
RUN cd src && mvn clean install
"""
        passed, violations = validate_containerfile(cf, "org.example:project:1.0")
        assert passed is True


# ---------------------------------------------------------------------------
# check_build_log tests
# ---------------------------------------------------------------------------

class TestCheckBuildLog:
    def test_rejects_target_jar_download(self):
        log = """\
[INFO] Downloading https://repo1.maven.org/maven2/commons-io/commons-io/2.11.0/commons-io-2.11.0.jar
[INFO] Downloaded commons-io-2.11.0.jar (200 KB)
"""
        passed, details = check_build_log(log, "commons-io", "2.11.0")
        assert passed is False
        assert "commons-io-2.11.0.jar" in details

    def test_passes_dependency_jar_download(self):
        log = """\
[INFO] Downloading https://repo1.maven.org/maven2/org/slf4j/slf4j-api/1.7.36/slf4j-api-1.7.36.jar
[INFO] Downloaded slf4j-api-1.7.36.jar (30 KB)
[INFO] Downloading https://repo1.maven.org/maven2/junit/junit/4.13.2/junit-4.13.2.jar
"""
        passed, details = check_build_log(log, "commons-io", "2.11.0")
        assert passed is True
        assert details == ""

    def test_passes_clean_build_log(self):
        log = """\
[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) ---
[INFO] Compiling 42 source files to /build/target/classes
[INFO] BUILD SUCCESS
"""
        passed, details = check_build_log(log, "commons-io", "2.11.0")
        assert passed is True

    def test_rejects_wget_of_target_jar(self):
        log = "wget https://mirror.example.com/commons-io-2.11.0.jar\n"
        passed, details = check_build_log(log, "commons-io", "2.11.0")
        assert passed is False

    def test_rejects_curl_of_target_jar(self):
        log = "curl -O https://some-mirror.com/org/apache/commons/commons-io/2.11.0/commons-io-2.11.0.jar\n"
        passed, details = check_build_log(log, "commons-io", "2.11.0")
        assert passed is False

    def test_empty_log_passes(self):
        passed, details = check_build_log("", "commons-io", "2.11.0")
        assert passed is True


# ---------------------------------------------------------------------------
# save_build() L4 constraint tests
# ---------------------------------------------------------------------------

class TestSaveBuildL4Constraint:
    def test_l4_without_eval_result_raises(self):
        from buildroot.agent.build_store import save_build

        with pytest.raises(ValueError, match="L4.*eval_result"):
            save_build("g:a:1.0", "FROM jdk:17", 0.99, 4, "test")

    @patch("buildroot.agent.build_store._get_connection")
    def test_l4_with_eval_result_succeeds(self, mock_conn):
        mock_cursor = MagicMock()
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        from buildroot.agent.build_store import save_build

        result = save_build(
            "g:a:1.0", "FROM jdk:17", 0.99, 4, "test",
            eval_result={"l4_match": True, "reward": 0.99},
        )
        assert result is True

    @patch("buildroot.agent.build_store._get_connection")
    def test_l3_without_eval_result_ok(self, mock_conn):
        mock_cursor = MagicMock()
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        from buildroot.agent.build_store import save_build

        result = save_build("g:a:1.0", "FROM jdk:17", 0.50, 3, "test")
        assert result is True

    def test_l5_without_eval_result_raises(self):
        from buildroot.agent.build_store import save_build

        with pytest.raises(ValueError, match="L4.*eval_result"):
            save_build("g:a:1.0", "FROM jdk:17", 1.0, 5, "test")


# ---------------------------------------------------------------------------
# seed_builds_db tests
# ---------------------------------------------------------------------------

class TestSeedFromResults:
    def test_uses_eval_result_level(self, tmp_path):
        pkg_dir = tmp_path / "org_example_lib_1_0"
        pkg_dir.mkdir()
        (pkg_dir / "attempts.json").write_text(json.dumps({
            "coordinate": "org.example:lib:1.0",
            "best_reward": 0.99,
            "status": "success",
            "method": "v4-agent",
        }))
        (pkg_dir / "Containerfile.best").write_text("FROM jdk:17\nRUN mvn install")
        (pkg_dir / "eval_result.json").write_text(json.dumps({
            "level_reached": 4,
            "l4_match": True,
            "reward": 0.99,
        }))

        from scripts.seed_builds_db import seed_from_results

        with patch("buildroot.agent.build_store.save_build") as mock_save:
            mock_save.return_value = True
            count = seed_from_results(tmp_path)

        assert count == 1
        call_args = mock_save.call_args
        assert call_args[0][3] == 4  # level from eval_result
        assert call_args[1]["eval_result"]["level_reached"] == 4

    def test_skips_without_eval_result(self, tmp_path):
        pkg_dir = tmp_path / "org_example_lib_2_0"
        pkg_dir.mkdir()
        (pkg_dir / "attempts.json").write_text(json.dumps({
            "coordinate": "org.example:lib:2.0",
            "best_reward": 0.99,
            "status": "success",
            "method": "v4-seed",
        }))
        (pkg_dir / "Containerfile.best").write_text("FROM jdk:17\nRUN wget ...")

        from scripts.seed_builds_db import seed_from_results

        with patch("buildroot.agent.build_store.save_build") as mock_save:
            count = seed_from_results(tmp_path)

        assert count == 0
        mock_save.assert_not_called()


class TestSeedFromKB:
    def test_uses_eval_result_level(self, tmp_path):
        pytest.importorskip("yaml")
        import yaml

        kb_file = tmp_path / "test_entry.yaml"
        kb_file.write_text(yaml.dump({
            "coordinate": "org.example:lib:1.0",
            "containerfile": "FROM jdk:17\nRUN mvn install",
            "l4_score": 0.99,
            "eval_result": {"level_reached": 4, "reward": 0.99},
        }))

        from scripts.seed_builds_db import seed_from_kb

        with patch("buildroot.agent.build_store.save_build") as mock_save:
            mock_save.return_value = True
            count = seed_from_kb(tmp_path)

        assert count == 1
        call_args = mock_save.call_args
        assert call_args[0][3] == 4
        assert call_args[1]["eval_result"]["level_reached"] == 4

    def test_skips_without_eval_result(self, tmp_path):
        pytest.importorskip("yaml")
        import yaml

        kb_file = tmp_path / "no_eval.yaml"
        kb_file.write_text(yaml.dump({
            "coordinate": "org.example:lib:2.0",
            "containerfile": "FROM jdk:17\nRUN wget ...",
            "l4_score": 1.0,
        }))

        from scripts.seed_builds_db import seed_from_kb

        with patch("buildroot.agent.build_store.save_build") as mock_save:
            count = seed_from_kb(tmp_path)

        assert count == 0
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# evaluate() integration tests — gate ordering
# ---------------------------------------------------------------------------

class TestEvaluateGateOrdering:
    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_cf_validation_before_build(self, mock_run):
        """validate_containerfile is called before _l2_build — a failing CF never builds."""
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN wget https://repo1.maven.org/maven2/axis/axis/1.4/axis-1.4.jar
"""
        evaluator = Evaluator()
        result = evaluator.evaluate(cf, "axis:axis:1.4")
        assert result.cf_validation_passed is False
        assert result.l4_signal_source == "anticheat_rejected"
        assert result.l1_parse is True
        assert result.l2_build is False
        mock_run.assert_not_called()

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_cf_passes_build_log_fails(self, mock_run):
        """A CF that passes validation but whose build log shows target download is rejected."""
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN git clone https://github.com/apache/commons-io.git src
RUN cd src && mvn clean install -DskipTests
"""
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stdout="Downloading https://repo1.maven.org/maven2/commons-io/commons-io/2.11.0/commons-io-2.11.0.jar\nBUILD SUCCESS",
                stderr="",
            ),
            MagicMock(
                returncode=0,
                stdout="target/commons-io-2.11.0.jar\nBUILD_SUCCESS",
                stderr="",
            ),
        ]

        evaluator = Evaluator()
        result = evaluator.evaluate(cf, "commons-io:commons-io:2.11.0")

        assert result.cf_validation_passed is True
        assert result.l2_build is True
        assert result.l3_command is True
        assert result.build_log_check_passed is False
        assert result.l4_signal_source == "anticheat_rejected"

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_legitimate_build_passes_all_gates(self, mock_run):
        """A legitimate build passes CF validation and build log check."""
        cf = """\
FROM eclipse-temurin:17-jdk
WORKDIR /build
RUN git clone https://github.com/apache/activemq.git src
RUN cd src && mvn clean install -DskipTests -pl activemq-client-jakarta
RUN cp src/activemq-client-jakarta/target/activemq-client-jakarta-5.18.3.jar /output/rebuilt.jar
"""
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stdout="[INFO] Compiling 42 source files\n[INFO] BUILD SUCCESS",
                stderr="",
            ),
            MagicMock(
                returncode=0,
                stdout="BUILD_SUCCESS",
                stderr="",
            ),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        evaluator = Evaluator()
        with patch.object(evaluator, "_l4_match"):
            result = evaluator.evaluate(cf, "org.apache.activemq:activemq-client-jakarta:5.18.3")

        assert result.cf_validation_passed is True
        assert result.build_log_check_passed is True
        assert result.l1_parse is True
        assert result.l2_build is True
        assert result.l3_command is True

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_cf_failure_short_circuits_no_l4_match(self, mock_run):
        """When CF validation fails, _l4_match is never reached."""
        cf = """\
FROM eclipse-temurin:17-jdk
RUN wget https://repo1.maven.org/maven2/org/example/lib/1.0/lib-1.0.jar
"""
        evaluator = Evaluator()
        with patch.object(evaluator, "_l4_match") as mock_l4:
            result = evaluator.evaluate(cf, "org.example:lib:1.0")
            mock_l4.assert_not_called()

        assert result.cf_validation_passed is False
        assert result.l2_build is False


class TestEvalResultAntiCheatFields:
    def test_to_dict_includes_cf_validation(self):
        result = EvalResult(
            l1_parse=True,
            cf_validation_passed=False,
            cf_violations=["JAR download detected", "No source acquisition"],
            l4_signal_source="anticheat_rejected",
        )
        d = result.to_dict()
        assert d["cf_validation_passed"] is False
        assert "JAR download" in d["cf_violations"][0]

    def test_to_dict_includes_build_log_check(self):
        result = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            build_log_check_passed=False,
            l4_signal_source="anticheat_rejected",
        )
        d = result.to_dict()
        assert d["build_log_check_passed"] is False

    def test_to_dict_omits_none_values(self):
        result = EvalResult(l1_parse=True)
        d = result.to_dict()
        assert "cf_validation_passed" not in d
        assert "cf_violations" not in d
        assert "build_log_check_passed" not in d
