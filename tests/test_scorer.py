"""Tests for the multi-signal fallback scorer."""

from __future__ import annotations

import struct
import tempfile
import zipfile
from pathlib import Path

import pytest

from buildroot.agent.models import EvalResult
from buildroot.agent.scorer import (
    ScoreBreakdown,
    _jdk_version_to_bytecode_major,
    build_score_breakdown,
    check_bytecode_version_match,
    check_manifest_sanity,
    check_structural_match,
    compute_fallback_score,
)


class TestScoreBreakdown:
    def test_basic_construction(self):
        bd = ScoreBreakdown(l1_parse=True, l2_build=True, l3_command=True)
        assert bd.l1_parse is True
        assert bd.jar_available is False
        assert bd.signal_source == ""

    def test_to_dict(self):
        bd = ScoreBreakdown(
            l1_parse=True, l2_build=True, l3_command=True,
            jar_available=True, l4_score=0.85,
            signal_source="full_comparison", reward=0.925, level_reached=3,
        )
        d = bd.to_dict()
        assert d["l4_score"] == 0.85
        assert d["signal_source"] == "full_comparison"
        assert d["reward"] == 0.925


class TestBuildScoreBreakdown:
    def test_full_comparison_path(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True,
                       l4_score=0.8, reward=0.75, level_reached=3,
                       l4_signal_source="full_comparison")
        bd = build_score_breakdown(er, "org.example:test:1.0")
        assert bd.jar_available is True
        assert bd.signal_source == "full_comparison"

    def test_fallback_path(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True,
                       l4_score=0.6, reward=0.8, level_reached=3,
                       l4_signal_source="fallback_signals",
                       bytecode_version_match=True,
                       manifest_sanity=True,
                       unit_tests_pass=False,
                       structural_match=0.5)
        bd = build_score_breakdown(er, "org.example:test:1.0")
        assert bd.jar_available is False
        assert bd.signal_source == "fallback_signals"
        assert bd.bytecode_version_match is True
        assert bd.manifest_sanity is True
        assert bd.unit_tests_pass is False
        assert bd.structural_match == 0.5
        assert bd.l4_score == 0.6

    def test_fallback_path_no_signals(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True,
                       l4_score=0.0, reward=0.5, level_reached=3)
        bd = build_score_breakdown(er, "org.example:test:1.0")
        assert bd.jar_available is False
        assert bd.signal_source == "fallback_signals"

    def test_l3_ceiling_path(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=False,
                       reward=0.15, level_reached=2)
        bd = build_score_breakdown(er, "org.example:test:1.0")
        assert bd.signal_source == "l3_ceiling"


class TestComputeFallbackScore:
    def test_both_pass(self):
        score = compute_fallback_score(True, True)
        assert score == pytest.approx(1.0)

    def test_both_fail(self):
        score = compute_fallback_score(False, False)
        assert score == pytest.approx(0.0)

    def test_bytecode_only(self):
        score = compute_fallback_score(True, False)
        assert score == pytest.approx(0.60)

    def test_manifest_only(self):
        score = compute_fallback_score(False, True)
        assert score == pytest.approx(0.40)

    def test_none_bytecode(self):
        score = compute_fallback_score(None, True)
        assert score == pytest.approx(0.40)

    def test_none_manifest(self):
        score = compute_fallback_score(True, None)
        assert score == pytest.approx(0.60)

    def test_both_none(self):
        score = compute_fallback_score(None, None)
        assert score == pytest.approx(0.0)

    def test_inactive_signals_ignored(self):
        # structural_match and unit_tests_pass are accepted but not scored
        score = compute_fallback_score(True, True, True, 1.0)
        assert score == pytest.approx(1.0)
        score = compute_fallback_score(True, True, False, 0.0)
        assert score == pytest.approx(1.0)

    def test_backward_compat_3_args(self):
        score = compute_fallback_score(True, True, True)
        assert 0.0 <= score <= 1.0


def _create_jar_with_class(jar_path: Path, major_version: int = 61) -> None:
    """Create a minimal JAR with a .class file having the specified major version."""
    class_header = b"\xca\xfe\xba\xbe"  # magic
    class_header += struct.pack(">H", 0)  # minor version
    class_header += struct.pack(">H", major_version)  # major version
    class_header += b"\x00" * 100  # padding

    manifest = b"Manifest-Version: 1.0\nCreated-By: test\n"

    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", manifest)
        zf.writestr("com/example/Main.class", class_header)


class TestCheckBytecodeVersionMatch:
    def test_matching_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            _create_jar_with_class(jar, major_version=61)  # JDK 17
            assert check_bytecode_version_match(jar, "17") is True

    def test_mismatching_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            _create_jar_with_class(jar, major_version=55)  # JDK 11
            assert check_bytecode_version_match(jar, "17") is False

    def test_jdk8_matching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            _create_jar_with_class(jar, major_version=52)  # JDK 8
            assert check_bytecode_version_match(jar, "8") is True
            assert check_bytecode_version_match(jar, "1.8") is True

    def test_nonexistent_jar(self):
        assert check_bytecode_version_match(Path("/nonexistent.jar"), "17") is None

    def test_invalid_jdk_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            _create_jar_with_class(jar, major_version=61)
            assert check_bytecode_version_match(jar, "invalid") is None


class TestCheckManifestSanity:
    def test_sane_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            with zipfile.ZipFile(jar, "w") as zf:
                zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
                zf.writestr(
                    "META-INF/maven/org.example/test/pom.properties",
                    "groupId=org.example\nartifactId=test\nversion=1.0\n",
                )
            assert check_manifest_sanity(jar, "org.example", "test") is True

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            with zipfile.ZipFile(jar, "w") as zf:
                zf.writestr("com/example/Main.class", b"\x00" * 10)
            assert check_manifest_sanity(jar, "org.example", "test") is False

    def test_missing_manifest_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            with zipfile.ZipFile(jar, "w") as zf:
                zf.writestr("META-INF/MANIFEST.MF", "Created-By: test\n")
            assert check_manifest_sanity(jar, "org.example", "test") is False

    def test_wrong_gav_in_properties(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar = Path(tmpdir) / "test.jar"
            with zipfile.ZipFile(jar, "w") as zf:
                zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
                zf.writestr(
                    "META-INF/maven/org.example/test/pom.properties",
                    "groupId=com.other\nartifactId=wrong\n",
                )
            assert check_manifest_sanity(jar, "org.example", "test") is False

    def test_nonexistent_jar(self):
        assert check_manifest_sanity(Path("/nonexistent.jar"), "org.example", "test") is None


class TestJdkVersionToBytecode:
    def test_modern_versions(self):
        assert _jdk_version_to_bytecode_major("17") == 61
        assert _jdk_version_to_bytecode_major("11") == 55
        assert _jdk_version_to_bytecode_major("21") == 65

    def test_legacy_versions(self):
        assert _jdk_version_to_bytecode_major("1.8") == 52
        assert _jdk_version_to_bytecode_major("1.7") == 51

    def test_minor_version_stripped(self):
        assert _jdk_version_to_bytecode_major("17.0.9") == 61
        assert _jdk_version_to_bytecode_major("11.0.20") == 55

    def test_invalid(self):
        assert _jdk_version_to_bytecode_major("invalid") is None
        assert _jdk_version_to_bytecode_major("") is None


class TestCheckStructuralMatch:
    def _make_jar_and_source(self, tmpdir, classes, java_files, pom_content=None):
        """Helper to create a JAR with classes and a source tree with .java files."""
        jar_path = Path(tmpdir) / "test.jar"
        source_root = Path(tmpdir) / "source"
        source_root.mkdir()

        manifest = b"Manifest-Version: 1.0\n"
        with zipfile.ZipFile(jar_path, "w") as zf:
            zf.writestr("META-INF/MANIFEST.MF", manifest)
            for cls in classes:
                zf.writestr(cls, b"\xca\xfe\xba\xbe" + b"\x00" * 20)

        for java in java_files:
            java_path = source_root / java
            java_path.parent.mkdir(parents=True, exist_ok=True)
            java_path.write_text("class Stub {}")

        if pom_content:
            (source_root / "pom.xml").write_text(pom_content)

        return jar_path, source_root

    def test_perfect_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Main.class", "com/example/Util.class"],
                ["src/main/java/com/example/Main.java", "src/main/java/com/example/Util.java"],
            )
            score = check_structural_match(jar, src)
            assert score == pytest.approx(1.0)

    def test_partial_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Main.class", "com/example/Extra.class"],
                ["src/main/java/com/example/Main.java", "src/main/java/com/example/Other.java"],
            )
            score = check_structural_match(jar, src)
            assert score is not None
            assert 0.0 < score < 1.0

    def test_inner_classes_map_to_outer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Foo.class", "com/example/Foo$Bar.class",
                 "com/example/Foo$1.class"],
                ["src/main/java/com/example/Foo.java"],
            )
            score = check_structural_match(jar, src)
            assert score == pytest.approx(1.0)

    def test_no_source_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Main.class"],
                [],
            )
            score = check_structural_match(jar, src)
            assert score is None

    def test_no_classes_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar_path = Path(tmpdir) / "test.jar"
            source_root = Path(tmpdir) / "source"
            source_root.mkdir()
            with zipfile.ZipFile(jar_path, "w") as zf:
                zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
            java_path = source_root / "src/main/java/com/example/Main.java"
            java_path.parent.mkdir(parents=True, exist_ok=True)
            java_path.write_text("class Main {}")
            score = check_structural_match(jar_path, source_root)
            assert score is None

    def test_shaded_jar_returns_none(self):
        pom = """<?xml version="1.0"?>
<project>
  <build><plugins>
    <plugin><artifactId>maven-shade-plugin</artifactId></plugin>
  </plugins></build>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Main.class"],
                ["src/main/java/com/example/Main.java"],
                pom_content=pom,
            )
            score = check_structural_match(jar, src)
            assert score is None

    def test_bundle_plugin_returns_none(self):
        pom = """<?xml version="1.0"?>
<project>
  <build><plugins>
    <plugin><artifactId>maven-bundle-plugin</artifactId></plugin>
  </plugins></build>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Main.class"],
                ["src/main/java/com/example/Main.java"],
                pom_content=pom,
            )
            score = check_structural_match(jar, src)
            assert score is None

    def test_nonexistent_jar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            score = check_structural_match(
                Path(tmpdir) / "nope.jar", Path(tmpdir),
            )
            assert score is None

    def test_module_info_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Main.class", "module-info.class"],
                ["src/main/java/com/example/Main.java"],
            )
            score = check_structural_match(jar, src)
            assert score == pytest.approx(1.0)

    def test_meta_inf_classes_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jar, src = self._make_jar_and_source(
                tmpdir,
                ["com/example/Main.class", "META-INF/versions/9/com/example/Main.class"],
                ["src/main/java/com/example/Main.java"],
            )
            score = check_structural_match(jar, src)
            assert score == pytest.approx(1.0)
