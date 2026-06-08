"""JDK version inference with priority heuristic."""

from __future__ import annotations

import logging
import re

from buildroot.pipeline.models import (
    CIData,
    Confidence,
    JdkSpec,
    PomData,
    Source,
)

logger = logging.getLogger(__name__)

DISTRIBUTION_IMAGE_MAP = {
    "temurin": "eclipse-temurin",
    "adopt": "eclipse-temurin",
    "adopt-hotspot": "eclipse-temurin",
    "corretto": "amazoncorretto",
    "zulu": "azul/zulu-openjdk",
    "liberica": "bellsoft/liberica-openjdk-debian",
    "oracle": "container-registry.oracle.com/java/openjdk",
    "graalvm": "ghcr.io/graalvm/jdk",
}

DEFAULT_DISTRIBUTION = "temurin"
DEFAULT_IMAGE_BASE = "eclipse-temurin"
DEFAULT_JDK_VERSION = "17"

JAVA_HOME_VERSION_RE = re.compile(r"JAVA_HOME_(\d+)_")


class JdkResolver:
    """Resolve JDK version and distribution from multiple sources."""

    def resolve(
        self,
        pom_data: PomData,
        ci_data: CIData | None,
        resolved_properties: dict[str, str],
    ) -> JdkSpec:
        spec = JdkSpec()
        all_signals: list[dict[str, str]] = []

        # Priority 1: CI setup-java java-version + distribution
        if ci_data and ci_data.java_version:
            version = str(ci_data.java_version.value)
            if version:
                spec.version = version
                spec.confidence = Confidence(
                    level=Source.OBSERVED,
                    reason="JDK version from CI setup-java action",
                )
                spec.source_description = ci_data.java_version.description
                all_signals.append({
                    "source": "CI setup-java",
                    "version": version,
                    "priority": "1",
                })

        if ci_data and ci_data.distribution:
            dist = str(ci_data.distribution.value).lower()
            if dist:
                spec.distribution = dist
                all_signals.append({
                    "source": "CI setup-java distribution",
                    "distribution": dist,
                    "priority": "1",
                })

        # Priority 2: CI JAVA_HOME_* env var references
        if not spec.version and ci_data:
            version = self._check_java_home_env(ci_data)
            if version:
                spec.version = version
                spec.confidence = Confidence(
                    level=Source.OBSERVED,
                    reason="JDK version from CI JAVA_HOME env var",
                )
                spec.source_description = "JAVA_HOME env var in CI"
                all_signals.append({
                    "source": "CI JAVA_HOME env",
                    "version": version,
                    "priority": "2",
                })

        # Priority 3: POM maven.compiler.release
        pom_version = self._check_pom_compiler_release(resolved_properties)
        if pom_version:
            all_signals.append({
                "source": "maven.compiler.release",
                "version": pom_version,
                "priority": "3",
            })
            if not spec.version:
                spec.version = pom_version
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="JDK version from maven.compiler.release property",
                )
                spec.source_description = "POM maven.compiler.release"

        # Priority 4: POM maven.compiler.source/target
        pom_source = self._check_pom_compiler_source(resolved_properties)
        if pom_source:
            all_signals.append({
                "source": "maven.compiler.source",
                "version": pom_source,
                "priority": "4",
            })
            if not spec.version:
                spec.version = pom_source
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="JDK version from maven.compiler.source property",
                )
                spec.source_description = "POM maven.compiler.source"

        # Priority 5: maven-compiler-plugin <release> config
        plugin_release = self._check_compiler_plugin_release(pom_data)
        if plugin_release:
            all_signals.append({
                "source": "maven-compiler-plugin release",
                "version": plugin_release,
                "priority": "5",
            })
            if not spec.version:
                spec.version = plugin_release
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="JDK version from maven-compiler-plugin release config",
                )
                spec.source_description = "maven-compiler-plugin <release>"

        # Priority 6: maven-compiler-plugin <source> config
        plugin_source = self._check_compiler_plugin_source(pom_data)
        if plugin_source:
            all_signals.append({
                "source": "maven-compiler-plugin source",
                "version": plugin_source,
                "priority": "6",
            })
            if not spec.version:
                spec.version = plugin_source
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="JDK version from maven-compiler-plugin source config",
                )
                spec.source_description = "maven-compiler-plugin <source>"

        # Priority 7: Spring Boot java.version property
        spring_version = self._check_spring_boot_java_version(resolved_properties)
        if spring_version:
            all_signals.append({
                "source": "Spring Boot java.version",
                "version": spring_version,
                "priority": "7",
            })
            if not spec.version:
                spec.version = spring_version
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="JDK version from Spring Boot java.version property",
                )
                spec.source_description = "POM java.version (Spring Boot)"

        # Priority 8: Maven Enforcer requireJavaVersion
        enforcer_version = self._check_enforcer_rule(pom_data)
        if enforcer_version:
            all_signals.append({
                "source": "Maven Enforcer requireJavaVersion",
                "version": enforcer_version,
                "priority": "8",
            })
            if not spec.version:
                spec.version = enforcer_version
                spec.confidence = Confidence(
                    level=Source.INFERRED,
                    reason="JDK version from Maven Enforcer requireJavaVersion rule",
                )
                spec.source_description = "Maven Enforcer requireJavaVersion"

        # Priorities 9-11: .java-version, .sdkmanrc, .tool-versions
        # These are file-based and checked from CI data env vars or repo files
        if ci_data:
            for file_source, file_key in [
                (".java-version", "9"),
                (".sdkmanrc", "10"),
                (".tool-versions", "11"),
            ]:
                file_version = ci_data.env_vars.get(f"_buildroot_{file_source}")
                if file_version:
                    all_signals.append({
                        "source": file_source,
                        "version": file_version,
                        "priority": file_key,
                    })
                    if not spec.version:
                        spec.version = file_version
                        spec.confidence = Confidence(
                            level=Source.OBSERVED,
                            reason=f"JDK version from {file_source} file",
                        )
                        spec.source_description = f"{file_source} file in repo"

        # Priority 12: Default
        if not spec.version:
            spec.version = DEFAULT_JDK_VERSION
            spec.confidence = Confidence(
                level=Source.DEFAULTED,
                reason="No JDK version signal found; defaulting to JDK 17",
            )
            spec.source_description = "Default (no signal found)"

        if not spec.distribution:
            spec.distribution = DEFAULT_DISTRIBUTION

        spec.base_image = self._map_distribution_to_image(
            spec.distribution, spec.version
        )

        spec.conflicts = self._detect_conflicts(all_signals)

        return spec

    def _check_java_home_env(self, ci_data: CIData) -> str:
        for key in ci_data.env_vars:
            m = JAVA_HOME_VERSION_RE.search(key)
            if m:
                return m.group(1)
        return ""

    def _check_pom_compiler_release(self, props: dict[str, str]) -> str:
        return props.get("maven.compiler.release", "")

    def _check_pom_compiler_source(self, props: dict[str, str]) -> str:
        return props.get("maven.compiler.source", "")

    def _check_compiler_plugin_release(self, pom_data: PomData) -> str:
        for plugin in pom_data.build_plugins:
            if plugin.get("artifactId") == "maven-compiler-plugin":
                config = plugin.get("configuration", {})
                if "release" in config:
                    return config["release"]
        return ""

    def _check_compiler_plugin_source(self, pom_data: PomData) -> str:
        for plugin in pom_data.build_plugins:
            if plugin.get("artifactId") == "maven-compiler-plugin":
                config = plugin.get("configuration", {})
                if "source" in config:
                    return config["source"]
        return ""

    def _check_spring_boot_java_version(self, props: dict[str, str]) -> str:
        return props.get("java.version", "")

    def _check_enforcer_rule(self, pom_data: PomData) -> str:
        for plugin in pom_data.build_plugins:
            if plugin.get("artifactId") == "maven-enforcer-plugin":
                config = plugin.get("configuration", {})
                for key in ("requireJavaVersion", "source"):
                    if key in config:
                        version_str = config[key]
                        cleaned = re.sub(r"[\[\](,)]", "", version_str).strip()
                        if cleaned:
                            return cleaned.split(",")[0].strip()
        return ""

    def _map_distribution_to_image(self, distribution: str, version: str) -> str:
        dist_lower = distribution.lower()
        image_base = DISTRIBUTION_IMAGE_MAP.get(dist_lower, DEFAULT_IMAGE_BASE)
        tag_version = self._normalize_version_for_tag(version)
        return f"{image_base}:{tag_version}"

    @staticmethod
    def _normalize_version_for_tag(version: str) -> str:
        """Normalize JDK version for Docker image tags (1.8 -> 8, 1.7 -> 7)."""
        if version.startswith("1.") and len(version) >= 3:
            return version[2:]
        return version

    def _detect_conflicts(self, signals: list[dict[str, str]]) -> list[dict[str, str]]:
        versions = {}
        for sig in signals:
            v = sig.get("version", "")
            if v:
                versions.setdefault(v, []).append(sig["source"])

        if len(versions) <= 1:
            return []

        conflicts = []
        for version, sources in versions.items():
            conflicts.append({
                "version": version,
                "sources": ", ".join(sources),
            })
        return conflicts
