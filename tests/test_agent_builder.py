"""Tests for GHA sanitization (relocated from builder to analyzer)."""

from buildroot.agent.analyzer import sanitize_gha_expressions


class TestSanitizeGhaExpressions:
    def test_strips_secrets(self):
        line = "ARG TOKEN=${{ secrets.GITHUB_TOKEN }}"
        result = sanitize_gha_expressions(line)
        assert "${{" not in result
        assert "ARG TOKEN=" in result

    def test_strips_tojson(self):
        line = "ENV DATA=${{ toJSON(github.event) }}"
        result = sanitize_gha_expressions(line)
        assert "${{" not in result
        assert "ENV DATA=" in result

    def test_strips_github_context(self):
        line = "ENV REF=${{ github.ref }}"
        result = sanitize_gha_expressions(line)
        assert "${{" not in result

    def test_preserves_clean_lines(self):
        lines = "FROM ubuntu:22.04\nRUN apt-get update\nENV JAVA_HOME=/usr/lib/jvm/java-17"
        result = sanitize_gha_expressions(lines)
        assert result == lines

    def test_removes_non_arg_env_lines_if_only_expression(self):
        containerfile = (
            "FROM ubuntu:22.04\n"
            "RUN echo ${{ github.actor }}\n"
            "RUN apt-get update"
        )
        result = sanitize_gha_expressions(containerfile)
        assert "${{" not in result

    def test_handles_multiple_expressions_in_multiline(self):
        containerfile = (
            "FROM ubuntu:22.04\n"
            "ARG TOKEN=${{ secrets.TOKEN }}\n"
            "ARG REF=${{ github.ref }}\n"
            "ENV FOO=bar\n"
        )
        result = sanitize_gha_expressions(containerfile)
        assert "${{" not in result
        assert "ENV FOO=bar" in result

    def test_empty_input(self):
        assert sanitize_gha_expressions("") == ""

    def test_no_expressions(self):
        cf = "FROM docker.io/library/maven:3.9\nRUN mvn clean install"
        assert sanitize_gha_expressions(cf) == cf
