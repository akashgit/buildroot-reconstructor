"""Tests for trusted source config loading."""

from __future__ import annotations

from pathlib import Path

from buildroot.trust.config import DEFAULT_TRUST_CONFIG, load_trust_config


class TestDefaultConfig:
    def test_default_provider_is_adoptium(self):
        assert DEFAULT_TRUST_CONFIG["default_tier1_provider"] == "adoptium"

    def test_default_strategy(self):
        assert DEFAULT_TRUST_CONFIG["jdk_resolution_strategy"] == "nearest_lts_above"

    def test_default_dual_build_enabled(self):
        assert DEFAULT_TRUST_CONFIG["dual_build"] is True

    def test_default_sources_present(self):
        sources = DEFAULT_TRUST_CONFIG["sources"]
        assert "adoptium" in sources
        assert "redhat_ubi" in sources
        assert "corretto" in sources
        assert "jdk_archive" in sources


class TestLoadTrustConfig:
    def test_no_factory_md_returns_defaults(self):
        config = load_trust_config()
        assert config["default_tier1_provider"] == "adoptium"
        assert "adoptium" in config["sources"]

    def test_override_provider(self):
        config = load_trust_config(override={"default_tier1_provider": "redhat_ubi"})
        assert config["default_tier1_provider"] == "redhat_ubi"

    def test_override_strategy(self):
        config = load_trust_config(
            override={"jdk_resolution_strategy": "exact_only"}
        )
        assert config["jdk_resolution_strategy"] == "exact_only"

    def test_override_merges_sources(self):
        config = load_trust_config(override={
            "sources": {"chainguard": {"tier": 1, "jdk_versions": ["21"]}},
        })
        assert "chainguard" in config["sources"]
        assert "adoptium" in config["sources"]

    def test_nonexistent_factory_md(self, tmp_path: Path):
        config = load_trust_config(
            factory_md_path=tmp_path / "missing.md",
        )
        assert config["default_tier1_provider"] == "adoptium"

    def test_factory_md_with_trust_section(self, tmp_path: Path):
        md = tmp_path / "factory.md"
        md.write_text(
            "# Factory\n\n"
            "## Trusted Sources\n"
            "- default_provider: redhat_ubi\n"
            "- strategy: exact_only\n"
            "- dual_build: false\n"
            "\n## Other Section\n"
        )
        config = load_trust_config(factory_md_path=md)
        assert config["default_tier1_provider"] == "redhat_ubi"
        assert config["jdk_resolution_strategy"] == "exact_only"
        assert config["dual_build"] is False

    def test_factory_md_without_trust_section(self, tmp_path: Path):
        md = tmp_path / "factory.md"
        md.write_text("# Factory\n\n## Goal\nBuild stuff.\n")
        config = load_trust_config(factory_md_path=md)
        assert config["default_tier1_provider"] == "adoptium"

    def test_override_takes_precedence_over_factory_md(self, tmp_path: Path):
        md = tmp_path / "factory.md"
        md.write_text(
            "## Trusted Sources\n"
            "- default_provider: redhat_ubi\n"
        )
        config = load_trust_config(
            factory_md_path=md,
            override={"default_tier1_provider": "adoptium"},
        )
        assert config["default_tier1_provider"] == "adoptium"


class TestStrategyMapping:
    def test_all_strategies_valid(self):
        from buildroot.trust.registry import JdkResolutionStrategy

        assert JdkResolutionStrategy("nearest_lts_above") == JdkResolutionStrategy.NEAREST_LTS_ABOVE
        assert JdkResolutionStrategy("build_from_source") == JdkResolutionStrategy.BUILD_FROM_SOURCE
        assert JdkResolutionStrategy("exact_only") == JdkResolutionStrategy.EXACT_ONLY
