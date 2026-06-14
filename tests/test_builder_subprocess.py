"""Tests for Builder agent — Claude Code subprocess integration."""

from unittest.mock import patch

from buildroot.agent.builder import Builder, _extract_containerfile
from buildroot.agent.claude_runner import AgentResult
from buildroot.agent.models import DeadEndEntry


def _make_spec():
    """Create a minimal BuildrootSpec for testing."""
    from buildroot.pipeline.models import BuildrootSpec, JdkSpec, PomData

    return BuildrootSpec(
        source_repo="https://github.com/foo/bar",
        git_tag="v1.0",
        jdk_spec=JdkSpec(version="17", distribution="temurin"),
        maven_version="3.9.6",
        build_commands=["mvn clean install -DskipTests"],
        pom_data=PomData(),
    )


class TestExtractContainerfile:
    def test_plain_text(self):
        r = AgentResult(text="FROM maven:3.9\nRUN mvn install")
        assert _extract_containerfile(r) == "FROM maven:3.9\nRUN mvn install"

    def test_strips_markdown_fences(self):
        r = AgentResult(text="```dockerfile\nFROM maven:3.9\nRUN mvn install\n```")
        assert _extract_containerfile(r) == "FROM maven:3.9\nRUN mvn install"


class TestBuilderSubprocess:
    @patch("buildroot.agent.builder.spawn_claude_agent")
    def test_refine_calls_agent(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="FROM docker.io/library/maven:3.9-eclipse-temurin-17\nRUN mvn install",
        )
        builder = Builder(model="claude-opus-4-6", meta_guidance="Use JDK 17")
        result = builder.refine(
            containerfile="FROM maven:3.8\nRUN mvn install",
            error_class="compilation/jdk_mismatch",
            error_summary="javac: source 17 not supported",
            dead_ends=[],
            spec=_make_spec(),
        )
        assert "maven" in result
        assert mock_spawn.called
        call_kwargs = mock_spawn.call_args
        assert "Use JDK 17" in call_kwargs.kwargs.get("system_prompt", call_kwargs[1].get("system_prompt", ""))

    @patch("buildroot.agent.builder.spawn_claude_agent")
    def test_refine_preserves_containerfile_on_error(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="", is_error=True, error_message="timeout",
        )
        builder = Builder()
        original = "FROM maven:3.8\nRUN mvn install"
        result = builder.refine(
            containerfile=original,
            error_class="compilation/jdk_mismatch",
            error_summary="error",
            dead_ends=[],
            spec=_make_spec(),
        )
        assert result == original

    @patch("buildroot.agent.builder.spawn_claude_agent")
    def test_explore_calls_agent(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="FROM docker.io/library/ubuntu:22.04\nRUN apt-get install openjdk-17-jdk",
        )
        builder = Builder()
        result = builder.explore(
            containerfile="FROM maven:3.8\nRUN mvn install",
            spec=_make_spec(),
            error_class="compilation/jdk_mismatch",
            error_summary="error",
            dead_ends=[],
        )
        assert "ubuntu" in result

    @patch("buildroot.agent.builder.spawn_claude_agent")
    def test_fresh_start_calls_agent(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="FROM docker.io/library/maven:3.9-eclipse-temurin-17\nRUN mvn clean install",
        )
        builder = Builder()
        result = builder.fresh_start(spec=_make_spec())
        assert "maven" in result

    @patch("buildroot.agent.builder.spawn_claude_agent")
    def test_meta_guidance_in_system_prompt(self, mock_spawn):
        mock_spawn.return_value = AgentResult(text="FROM maven:3.9")
        builder = Builder(meta_guidance="Always use multi-stage builds")
        builder.refine(
            containerfile="FROM maven:3.8",
            error_class="test",
            error_summary="error",
            dead_ends=[],
            spec=_make_spec(),
        )
        system_prompt = mock_spawn.call_args.kwargs.get(
            "system_prompt", mock_spawn.call_args[1].get("system_prompt", "")
        )
        assert "multi-stage builds" in system_prompt

    @patch("buildroot.agent.builder.spawn_claude_agent")
    def test_gha_sanitization_applied(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="FROM maven:3.9\nARG TOKEN=${{ secrets.GITHUB_TOKEN }}\nRUN mvn install",
        )
        builder = Builder()
        result = builder.refine(
            containerfile="FROM maven:3.8",
            error_class="test",
            error_summary="error",
            dead_ends=[],
            spec=_make_spec(),
        )
        assert "${{" not in result

    @patch("buildroot.agent.builder.spawn_claude_agent")
    def test_dead_ends_included_in_task(self, mock_spawn):
        mock_spawn.return_value = AgentResult(text="FROM maven:3.9")
        de = DeadEndEntry(
            error_class="jdk_mismatch", approach="use jdk 8",
            failure_count=3, threshold=2,
        )
        builder = Builder()
        builder.refine(
            containerfile="FROM maven:3.8",
            error_class="test",
            error_summary="error",
            dead_ends=[de],
            spec=_make_spec(),
        )
        call_args = mock_spawn.call_args
        task = call_args.kwargs.get("task") or call_args[0][0]
        assert "DO NOT retry" in task
