"""Unit tests for PNC Containerfile template rendering."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "buildroot" / "generators" / "templates"


def _render_pnc_template(**kwargs) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("pnc_base.j2")
    defaults = {
        "pnc_builder_image": "quay.io/rh-newcastle/builder-rhel-7-j8-mvn3.6.3@sha256:abc123",
        "pnc_build_id": "12345",
        "source_repo": "https://github.com/apache/commons-lang.git",
        "git_tag": "rel/commons-lang-3.12.0",
        "timestamp": "2024-01-01T00:00:00Z",
        "build_command": "mvn clean install -B -DskipTests",
        "rhel_version": "7",
        "env_vars": {},
        "extra_build_flags": [],
    }
    defaults.update(kwargs)
    return template.render(**defaults)


class TestPncTemplate:
    def test_uses_builder_image(self):
        rendered = _render_pnc_template()
        assert "FROM quay.io/rh-newcastle/builder-rhel-7-j8-mvn3.6.3@sha256:abc123" in rendered

    def test_no_jdk_install(self):
        rendered = _render_pnc_template()
        assert "apt-get" not in rendered
        lines = rendered.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("RUN") and "install" in stripped and "java" in stripped.lower():
                pytest.fail(f"Found JDK install step: {stripped}")

    def test_no_maven_install(self):
        rendered = _render_pnc_template()
        assert "apache-maven-" not in rendered
        assert "MAVEN_HOME" not in rendered

    def test_git_clone(self):
        rendered = _render_pnc_template()
        assert "git clone --depth 1 --branch 'rel/commons-lang-3.12.0' 'https://github.com/apache/commons-lang.git' /build" in rendered

    def test_copy_fallback(self):
        rendered = _render_pnc_template(source_repo="", git_tag="")
        assert "COPY . ." in rendered
        assert "git clone" not in rendered

    def test_rhel7_yum(self):
        rendered = _render_pnc_template(rhel_version="7")
        assert "yum install -y git" in rendered
        assert "dnf" not in rendered

    def test_rhel8_dnf(self):
        rendered = _render_pnc_template(rhel_version="8")
        assert "dnf install -y git" in rendered
        assert "yum" not in rendered

    def test_rhel9_dnf(self):
        rendered = _render_pnc_template(rhel_version="9")
        assert "dnf install -y git" in rendered

    def test_source_date_epoch(self):
        rendered = _render_pnc_template()
        assert "SOURCE_DATE_EPOCH=946684800" in rendered

    def test_build_command(self):
        rendered = _render_pnc_template(build_command="mvn clean deploy -B")
        assert "RUN mvn clean deploy -B" in rendered

    def test_extra_build_flags(self):
        rendered = _render_pnc_template(
            build_command="mvn clean install",
            extra_build_flags=["-DskipTests", "-Dgpg.skip=true"],
        )
        assert "-DskipTests -Dgpg.skip=true" in rendered

    def test_env_vars(self):
        rendered = _render_pnc_template(env_vars={"JAVA_OPTS": "-Xmx512m"})
        assert "ENV JAVA_OPTS=-Xmx512m" in rendered

    def test_pnc_build_id_in_header(self):
        rendered = _render_pnc_template(pnc_build_id="12345")
        assert "PNC build 12345" in rendered or "12345" in rendered

    def test_jar_normalization_present(self):
        rendered = _render_pnc_template()
        assert "Normalize non-reproducible JAR metadata" in rendered
        assert "MANIFEST.MF" in rendered
