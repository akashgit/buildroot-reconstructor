"""Deterministic pre-pass — fast data gathering before the Analysis Agent runs."""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from buildroot.parsers.ci import CIParser
from buildroot.parsers.pom import PomParser
from buildroot.pipeline.models import PomData
from buildroot.pipeline.orchestrator import parse_gav
from buildroot.utils.github_api import discover_git_tag, discover_repo_from_pom
from buildroot.utils.maven_central import fetch_pom, get_jar_path

logger = logging.getLogger(__name__)

JDK_BYTECODE_MAJOR = {
    45: "1.1", 46: "1.2", 47: "1.3", 48: "1.4", 49: "5",
    50: "6", 51: "7", 52: "8", 53: "9", 54: "10",
    55: "11", 56: "12", 57: "13", 58: "14", 59: "15",
    60: "16", 61: "17", 62: "18", 63: "19", 64: "20",
    65: "21", 66: "22", 67: "23", 68: "24",
}


@dataclass
class PrePassFinding:
    """A single pre-pass finding with provenance."""

    value: Any
    source: str  # "pom_xml", "manifest", "ci_workflow", "maven_wrapper", "github_api"
    confidence: str  # "high", "medium", "low"
    evidence: str


@dataclass
class PrePassFindings:
    """All findings from the deterministic pre-pass."""

    source_repo: PrePassFinding | None = None
    git_tag: PrePassFinding | None = None
    jdk_version: PrePassFinding | None = None
    jdk_minor_version: PrePassFinding | None = None
    jdk_distribution: PrePassFinding | None = None
    build_system: PrePassFinding | None = None
    build_command: PrePassFinding | None = None
    use_maven_wrapper: PrePassFinding | None = None
    maven_version: PrePassFinding | None = None
    base_image: PrePassFinding | None = None
    module_path: PrePassFinding | None = None

    env_vars: dict[str, str] = field(default_factory=dict)
    pom_data: dict = field(default_factory=dict)
    ci_data: dict | None = None
    attempted_but_failed: list[str] = field(default_factory=list)

    jar_path: Path | None = None
    jar_unpacked_dir: Path | None = None
    jar_manifest: dict[str, str] = field(default_factory=dict)
    jar_entry_count: int | None = None
    bytecode_major_version: int | None = None

    def to_prompt(self) -> str:
        """Format findings for the Analysis Agent prompt."""
        sections: list[str] = []
        sections.append("## Pre-Pass Findings\n")

        finding_fields = [
            ("source_repo", self.source_repo),
            ("git_tag", self.git_tag),
            ("jdk_version", self.jdk_version),
            ("jdk_minor_version", self.jdk_minor_version),
            ("jdk_distribution", self.jdk_distribution),
            ("build_system", self.build_system),
            ("build_command", self.build_command),
            ("use_maven_wrapper", self.use_maven_wrapper),
            ("maven_version", self.maven_version),
            ("base_image", self.base_image),
            ("module_path", self.module_path),
        ]

        for name, finding in finding_fields:
            if finding is not None:
                sections.append(
                    f"- **{name}**: `{finding.value}` "
                    f"(source={finding.source}, confidence={finding.confidence})\n"
                    f"  Evidence: {finding.evidence}"
                )

        if self.env_vars:
            sections.append("\n### Environment Variables")
            for k, v in self.env_vars.items():
                sections.append(f"- {k}={v}")

        if self.jar_manifest:
            sections.append("\n### JAR Manifest")
            build_relevant = {
                "Build-Jdk", "Build-Jdk-Spec", "Created-By", "Bundle-Version",
                "Implementation-Version", "Specification-Version",
                "Maven-Version", "Built-By", "Manifest-Version",
            }
            for k, v in self.jar_manifest.items():
                v_str = str(v)
                if k in build_relevant or len(v_str) <= 200:
                    sections.append(f"- {k}: {v_str[:500]}")
                else:
                    sections.append(f"- {k}: [{len(v_str)} chars, truncated]")

        if self.bytecode_major_version is not None:
            jdk_label = JDK_BYTECODE_MAJOR.get(
                self.bytecode_major_version, f"unknown({self.bytecode_major_version})"
            )
            sections.append(
                f"\n### Bytecode\n- Major version: {self.bytecode_major_version} (JDK {jdk_label})"
            )

        if self.jar_entry_count is not None:
            sections.append(f"- JAR entry count: {self.jar_entry_count}")

        if self.jar_path:
            sections.append(f"\n### Artifact Paths\n- JAR: {self.jar_path}")
        if self.jar_unpacked_dir:
            sections.append(f"- Unpacked: {self.jar_unpacked_dir}")

        if self.attempted_but_failed:
            sections.append("\n### Attempted But Failed")
            for item in self.attempted_but_failed:
                sections.append(f"- {item}")

        if self.pom_data:
            sections.append("\n### POM Data (summary)")
            pd = self.pom_data
            if pd.get("group_id"):
                sections.append(f"- GAV: {pd.get('group_id')}:{pd.get('artifact_id')}:{pd.get('version')}")
            if pd.get("modules"):
                sections.append(f"- Modules: {pd['modules']}")
            if pd.get("build_plugins"):
                plugin_names = [p.get("artifactId", "?") for p in pd["build_plugins"][:10]]
                sections.append(f"- Build plugins: {', '.join(plugin_names)}")

        return "\n".join(sections)

    def to_dict(self) -> dict:
        """Convert to a serializable dict."""
        result: dict[str, Any] = {}
        for name in (
            "source_repo", "git_tag", "jdk_version", "jdk_minor_version",
            "jdk_distribution", "build_system", "build_command",
            "use_maven_wrapper", "maven_version", "base_image", "module_path",
        ):
            finding = getattr(self, name)
            if finding is not None:
                result[name] = {
                    "value": finding.value,
                    "source": finding.source,
                    "confidence": finding.confidence,
                    "evidence": finding.evidence,
                }
        if self.env_vars:
            result["env_vars"] = self.env_vars
        if self.jar_manifest:
            result["jar_manifest"] = self.jar_manifest
        if self.bytecode_major_version is not None:
            result["bytecode_major_version"] = self.bytecode_major_version
        if self.jar_entry_count is not None:
            result["jar_entry_count"] = self.jar_entry_count
        if self.attempted_but_failed:
            result["attempted_but_failed"] = self.attempted_but_failed
        return result


def run_prepass(coordinate: str, workspace: Path) -> PrePassFindings:
    """Run the deterministic pre-pass: POM parse, repo discovery, JAR extraction.

    Data-gathering only — no template rendering, no spec decisions.
    """
    group_id, artifact_id, version = parse_gav(coordinate)
    findings = PrePassFindings()

    # 1. Fetch and parse POM
    pom_parser = PomParser()
    try:
        pom_xml = fetch_pom(group_id, artifact_id, version)
        pom_data = pom_parser.parse(pom_xml)
        findings.pom_data = _pom_data_to_dict(pom_data)

        if pom_data.modules:
            findings.module_path = PrePassFinding(
                value=pom_data.modules[0] if len(pom_data.modules) == 1 else None,
                source="pom_xml",
                confidence="medium" if len(pom_data.modules) == 1 else "low",
                evidence=f"POM declares modules: {pom_data.modules}",
            )
    except Exception as e:
        logger.warning("POM fetch/parse failed: %s", e)
        findings.attempted_but_failed.append(f"POM fetch/parse: {e}")
        pom_data = PomData(group_id=group_id, artifact_id=artifact_id, version=version)

    # 2. Discover source repo
    try:
        repo_info = discover_repo_from_pom(pom_data)
        if repo_info:
            owner, name = repo_info
            repo_url = f"https://github.com/{owner}/{name}.git"
            findings.source_repo = PrePassFinding(
                value=repo_url,
                source="pom_xml",
                confidence="high" if pom_data.scm else "medium",
                evidence=f"SCM URL from POM → {owner}/{name}",
            )
        else:
            findings.attempted_but_failed.append("Source repo discovery: no SCM URL in POM")
    except Exception as e:
        logger.warning("Repo discovery failed: %s", e)
        findings.attempted_but_failed.append(f"Source repo discovery: {e}")

    # 3. Discover git tag
    if findings.source_repo:
        try:
            repo_url = findings.source_repo.value
            parts = repo_url.rstrip("/").rstrip(".git").split("/")
            owner, name = parts[-2], parts[-1]
            tag = discover_git_tag(owner, name, artifact_id, version)
            findings.git_tag = PrePassFinding(
                value=tag,
                source="github_api",
                confidence="high" if tag != f"v{version}" else "medium",
                evidence=f"GitHub tags API matched: {tag}",
            )
        except Exception as e:
            logger.warning("Git tag discovery failed: %s", e)
            findings.attempted_but_failed.append(f"Git tag discovery: {e}")

    # 4. Fetch JAR manifest for JDK version
    try:
        jar_path = get_jar_path(group_id, artifact_id, version)
        findings.jar_path = jar_path

        with zipfile.ZipFile(jar_path) as zf:
            findings.jar_entry_count = len(zf.namelist())

            # Extract manifest
            if "META-INF/MANIFEST.MF" in zf.namelist():
                manifest_text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
                findings.jar_manifest = _parse_manifest(manifest_text)

                build_jdk = findings.jar_manifest.get(
                    "Build-Jdk-Spec", findings.jar_manifest.get("Build-Jdk", "")
                )
                if build_jdk:
                    major = _extract_jdk_major(build_jdk)
                    findings.jdk_version = PrePassFinding(
                        value=major,
                        source="manifest",
                        confidence="high",
                        evidence=f"MANIFEST.MF Build-Jdk-Spec: {build_jdk}",
                    )
                    if "." in build_jdk and not build_jdk.startswith("1."):
                        findings.jdk_minor_version = PrePassFinding(
                            value=build_jdk,
                            source="manifest",
                            confidence="high",
                            evidence=f"MANIFEST.MF Build-Jdk: {build_jdk}",
                        )

                created_by = findings.jar_manifest.get("Created-By", "")
                if created_by:
                    minor = _extract_minor_version(created_by)
                    if minor and findings.jdk_minor_version is None:
                        findings.jdk_minor_version = PrePassFinding(
                            value=minor,
                            source="manifest",
                            confidence="medium",
                            evidence=f"MANIFEST.MF Created-By: {created_by}",
                        )

            # Extract bytecode major version from first .class file
            class_files = [n for n in zf.namelist() if n.endswith(".class") and not n.startswith("META-INF/")]
            if class_files:
                class_data = zf.read(class_files[0])
                if len(class_data) >= 8:
                    major_version = int.from_bytes(class_data[6:8], "big")
                    findings.bytecode_major_version = major_version

            # Unpack JAR
            unpack_dir = workspace / "original_jar"
            unpack_dir.mkdir(parents=True, exist_ok=True)
            for name in zf.namelist():
                target = unpack_dir / name
                resolved = target.resolve()
                if not resolved.is_relative_to(unpack_dir.resolve()):
                    continue
                if name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(name))
            findings.jar_unpacked_dir = unpack_dir

    except Exception as e:
        logger.warning("JAR download/extract failed: %s", e)
        findings.attempted_but_failed.append(f"JAR download/extract: {e}")

    # 5. CI workflow parsing (if repo discovered)
    if findings.source_repo:
        try:
            repo_url = findings.source_repo.value
            parts = repo_url.rstrip("/").rstrip(".git").split("/")
            owner, name = parts[-2], parts[-1]
            ci_parser = CIParser()
            ci_data = _try_parse_ci(ci_parser, owner, name)
            if ci_data:
                findings.ci_data = _ci_data_to_dict(ci_data)
                if ci_data.java_version and ci_data.java_version.value:
                    if findings.jdk_version is None:
                        findings.jdk_version = PrePassFinding(
                            value=str(ci_data.java_version.value),
                            source="ci_workflow",
                            confidence="medium",
                            evidence=f"CI workflow java-version: {ci_data.java_version.value}",
                        )
                if ci_data.build_commands:
                    findings.build_command = PrePassFinding(
                        value=ci_data.build_commands[0],
                        source="ci_workflow",
                        confidence="medium",
                        evidence=f"CI workflow build command: {ci_data.build_commands[0]}",
                    )
                if ci_data.env_vars:
                    findings.env_vars.update(ci_data.env_vars)
            else:
                findings.attempted_but_failed.append("CI workflow parse: no workflows found")
        except Exception as e:
            logger.warning("CI parse failed: %s", e)
            findings.attempted_but_failed.append(f"CI parse: {e}")

    # 6. Build system detection
    _detect_build_system_from_findings(findings, pom_data)

    # 7. JDK distribution inference
    if findings.jdk_version and findings.jdk_distribution is None:
        findings.jdk_distribution = PrePassFinding(
            value="temurin",
            source="manifest",
            confidence="low",
            evidence="Default distribution (most common on Maven Central)",
        )

    return findings


def _detect_build_system_from_findings(findings: PrePassFindings, pom_data: PomData) -> None:
    """Detect build system from POM plugins and CI commands."""
    build_cmd = findings.build_command.value if findings.build_command else ""

    if "gradlew" in build_cmd or "gradle " in build_cmd:
        findings.build_system = PrePassFinding(
            value="gradle", source="ci_workflow", confidence="high",
            evidence=f"CI build command uses Gradle: {build_cmd}",
        )
        return

    if "ant " in build_cmd:
        findings.build_system = PrePassFinding(
            value="ant", source="ci_workflow", confidence="high",
            evidence=f"CI build command uses Ant: {build_cmd}",
        )
        return

    for plugin in pom_data.build_plugins:
        aid = plugin.get("artifactId", "")
        if "gradle" in aid.lower():
            findings.build_system = PrePassFinding(
                value="gradle", source="pom_xml", confidence="medium",
                evidence=f"POM has Gradle-related plugin: {aid}",
            )
            return

    findings.build_system = PrePassFinding(
        value="maven", source="pom_xml", confidence="high",
        evidence="POM present, no Gradle/Ant indicators",
    )

    if "./mvnw" in build_cmd or "mvnw" in build_cmd:
        findings.use_maven_wrapper = PrePassFinding(
            value=True, source="ci_workflow", confidence="high",
            evidence=f"CI uses maven wrapper: {build_cmd}",
        )


def _try_parse_ci(ci_parser: CIParser, owner: str, name: str) -> Any:
    """Try to fetch and parse CI workflows from GitHub."""
    from buildroot.utils.github_api import fetch_file_content, list_directory

    workflow_files = list_directory(owner, name, ".github/workflows")
    if not workflow_files:
        return None

    for wf_entry in workflow_files[:3]:
        wf_file = wf_entry["name"] if isinstance(wf_entry, dict) else wf_entry
        if not wf_file.endswith((".yml", ".yaml")):
            continue
        content = fetch_file_content(owner, name, f".github/workflows/{wf_file}")
        if content:
            try:
                return ci_parser.parse_github_actions(content)
            except Exception:
                continue
    return None


def _parse_manifest(text: str) -> dict[str, str]:
    """Parse MANIFEST.MF into a dict."""
    entries: dict[str, str] = {}
    current_key: str | None = None
    current_val = ""
    for line in text.splitlines():
        if line.startswith(" ") and current_key is not None:
            current_val += line[1:]
        else:
            if current_key is not None:
                entries[current_key] = current_val
            if ":" in line:
                current_key, current_val = line.split(":", 1)
                current_key = current_key.strip()
                current_val = current_val.strip()
            else:
                current_key = None
                current_val = ""
    if current_key is not None:
        entries[current_key] = current_val
    return entries


def _extract_jdk_major(build_jdk: str) -> str:
    """Extract major JDK version from Build-Jdk-Spec or Build-Jdk."""
    parts = build_jdk.strip().split(".")
    if parts[0] == "1" and len(parts) >= 2:
        return parts[1]
    return parts[0]


def _extract_minor_version(created_by: str) -> str | None:
    """Extract minor JDK version from Created-By header."""
    import re
    m = re.search(r"(\d+\.\d+\.\d+)", created_by)
    if m:
        return m.group(1)
    return None


def _pom_data_to_dict(pom_data: PomData) -> dict:
    """Convert PomData to a plain dict."""
    return {
        "group_id": pom_data.group_id,
        "artifact_id": pom_data.artifact_id,
        "version": pom_data.version,
        "packaging": pom_data.packaging,
        "modules": pom_data.modules,
        "build_plugins": [
            {"groupId": p.get("groupId", ""), "artifactId": p.get("artifactId", "")}
            for p in pom_data.build_plugins[:15]
        ],
        "properties": dict(list(pom_data.properties.items())[:20]),
        "scm": pom_data.scm,
    }


def _ci_data_to_dict(ci_data: Any) -> dict:
    """Convert CIData to a plain dict."""
    result: dict[str, Any] = {}
    if ci_data.java_version:
        result["java_version"] = ci_data.java_version.value
    result["build_commands"] = ci_data.build_commands
    result["env_vars"] = ci_data.env_vars
    result["runner_os"] = ci_data.runner_os
    result["ci_type"] = ci_data.ci_type
    return result
