"""Pipeline orchestration — coordinates all extractors and generators."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import zipfile

import requests
from pathlib import Path

from buildroot.generators.containerfile import ContainerfileGenerator
from buildroot.parsers.ci import CIParser
from buildroot.parsers.pom import PomParser
from buildroot.parsers.properties import PropertyResolver
from buildroot.pipeline.models import BuildrootSpec, CIData, GapReport, PomData
from buildroot.resolvers.container_image import ContainerImageResolver
from buildroot.resolvers.dependencies import DependencyResolver
from buildroot.resolvers.jdk import JdkResolver
from buildroot.utils.github_api import (
    discover_git_tag,
    discover_repo_from_pom,
    fetch_maven_wrapper_properties,
)
from buildroot.utils.maven_central import fetch_pom, get_jar_path

logger = logging.getLogger(__name__)

_SHELL_UNSAFE_RE = re.compile(r"['\"`$\\;|&<>(){}!\n\r]")


def _sanitize_shell_value(s: str) -> str:
    return _SHELL_UNSAFE_RE.sub("", s)


def _has_flag(cmd: str, flag: str) -> bool:
    tokens = cmd.split()
    if flag.startswith("-D") or flag.startswith("-P"):
        prefix = flag.split("=")[0]
        return any(t == flag or t.startswith(prefix + "=") or t == prefix for t in tokens)
    return flag in tokens


_MAVEN_DIST_VERSION_RE = re.compile(
    r"apache-maven-(\d+\.\d+\.\d+)"
)


def _parse_maven_wrapper_version(content: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("distributionUrl") or line.startswith("wrapperUrl"):
            m = _MAVEN_DIST_VERSION_RE.search(line)
            if m:
                return m.group(1)
    return ""


def parse_gav(coordinate: str) -> tuple[str, str, str]:
    parts = coordinate.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"Invalid coordinate '{coordinate}': expected groupId:artifactId:version"
        )
    return parts[0], parts[1], parts[2]


class BuildrootOrchestrator:
    def __init__(self, *, no_cache: bool = False, skip_deps: bool = False, runtime: str = "podman", dual_build: bool = True):
        self._no_cache = no_cache
        self._skip_deps = skip_deps
        self._runtime = runtime
        self._dual_build = dual_build

    def reconstruct(
        self,
        group_id: str,
        artifact_id: str,
        version: str,
        *,
        repo_url: str | None = None,
        ci_type: str | None = None,
        output_dir: str | None = None,
    ) -> BuildrootSpec:
        out = Path(output_dir) if output_dir else Path(".")

        # 1. Fetch POM
        logger.info("Fetching POM for %s:%s:%s", group_id, artifact_id, version)
        xml_text = fetch_pom(group_id, artifact_id, version, no_cache=self._no_cache)

        # 2. Parse POM
        pom_parser = PomParser(no_cache=self._no_cache)
        pom_data = pom_parser.parse(xml_text)

        # 3. Resolve parent chain
        chain = pom_parser.resolve_parent_chain(pom_data)

        # 4. Merge POMs
        merged = pom_parser.merge_poms(chain)

        # 5. Resolve properties
        prop_resolver = PropertyResolver()
        resolved_props, prop_gaps = prop_resolver.resolve(merged)
        merged.properties = resolved_props

        # 6. Discover source repo
        repo_owner, repo_name = None, None
        source_repo = ""
        if repo_url:
            source_repo = repo_url
            parts = repo_url.rstrip("/").split("/")
            if len(parts) >= 2:
                repo_owner = parts[-2]
                repo_name = parts[-1]
        else:
            discovered = discover_repo_from_pom(merged)
            if discovered:
                repo_owner, repo_name = discovered
                source_repo = f"https://github.com/{repo_owner}/{repo_name}"
                logger.info("Discovered source repo: %s", source_repo)

        # 7. Discover and parse CI
        ci_data = None
        if repo_owner and repo_name:
            ci_parser = CIParser()
            if ci_type:
                detected_type = ci_type
                yaml_texts = self._fetch_ci_yamls(ci_parser, repo_owner, repo_name, ci_type)
            else:
                detected_type, yaml_texts = ci_parser.discover_ci_type(repo_owner, repo_name)

            if yaml_texts:
                if detected_type == "github":
                    for yt in yaml_texts:
                        parsed = ci_parser.parse_github_actions(yt)
                        if ci_data is None:
                            ci_data = parsed
                        else:
                            self._merge_ci_data(ci_data, parsed)
                elif detected_type == "circleci":
                    for yt in yaml_texts:
                        parsed = ci_parser.parse_circleci(yt)
                        if ci_data is None:
                            ci_data = parsed
                        else:
                            self._merge_ci_data(ci_data, parsed)

        # 8. Resolve JDK
        jdk_resolver = JdkResolver()
        jdk_spec = jdk_resolver.resolve(
            merged, ci_data, resolved_props,
            group_id=group_id, artifact_id=artifact_id, version=version,
        )

        # 9. Resolve container images if CI references one
        container_result = None
        if ci_data and ci_data.container_images:
            image_resolver = ContainerImageResolver()
            container_result = image_resolver.resolve(
                ci_data.container_images[0],
                repo_owner=repo_owner,
            )

        # 10. Resolve dependency tree
        dep_tree = None
        if not self._skip_deps:
            dep_resolver = DependencyResolver()
            dep_nodes = dep_resolver.resolve(
                group_id, artifact_id, version, skip_deps=self._skip_deps
            )
            if dep_nodes:
                from buildroot.pipeline.models import DependencyNode
                dep_tree = DependencyNode(
                    group_id=group_id,
                    artifact_id=artifact_id,
                    version=version,
                    children=dep_nodes,
                )

        # 11. Discover git tag
        if repo_owner and repo_name:
            git_tag = discover_git_tag(
                repo_owner, repo_name, artifact_id, version
            )
        else:
            git_tag = f"v{version}"

        # 12. Detect Maven wrapper version
        maven_version = ""
        if repo_owner and repo_name:
            maven_version = self._detect_maven_wrapper_version(
                repo_owner, repo_name
            )

        # 13. Build BuildrootSpec
        spec = BuildrootSpec(
            pom_data=merged,
            ci_data=ci_data,
            jdk_spec=jdk_spec,
            dependency_tree=dep_tree,
            source_repo=_sanitize_shell_value(source_repo),
            git_tag=_sanitize_shell_value(git_tag),
            maven_version=maven_version,
        )

        if ci_data:
            spec.build_commands = list(ci_data.build_commands)
            spec.system_packages = list(ci_data.system_packages)

        self._enrich_build_commands(spec, merged)

        if container_result:
            spec.base_image = container_result.get("base_image", "")

        # 12. Collect property gaps
        gap_report = GapReport()
        for entry in prop_gaps:
            gap_report.entries.append(entry)
        spec.gaps = gap_report

        # 13. Generate Containerfile and buildroot.json
        generator = ContainerfileGenerator()
        generator.generate(spec, out)

        # 14. Dual-variant trusted-source generation
        if self._dual_build:
            try:
                from buildroot.trust.config import load_trust_config
                from buildroot.trust.delta import build_delta_report
                from buildroot.trust.dual_variant import DualVariantGenerator
                from buildroot.trust.registry import TrustedSourceRegistry

                trust_config = load_trust_config()
                registry = TrustedSourceRegistry(trust_config)
                dual_gen = DualVariantGenerator(registry, generator)
                exact_result, trusted_result = dual_gen.generate_dual(spec, out)

                delta = build_delta_report(exact_result, trusted_result)
                delta.coordinate = f"{group_id}:{artifact_id}:{version}"
                delta_path = out / "delta_report.json"
                delta_path.write_text(
                    json.dumps(delta.to_dict(), indent=2) + "\n"
                )
                logger.info("Delta report written to %s", delta_path)

                from buildroot.trust.report import generate_trust_report

                trust_report_path = generate_trust_report(spec, delta, out)
                logger.info("Trust report written to %s", trust_report_path)
            except Exception:
                logger.warning(
                    "Dual-variant generation failed; exact variant is still available",
                    exc_info=True,
                )

        return spec

    def verify(
        self,
        group_id: str,
        artifact_id: str,
        version: str,
        *,
        rebuild: bool = False,
        output_dir: str | None = None,
    ) -> dict:
        out = Path(output_dir) if output_dir else Path(".")

        containerfile_path = out / "Containerfile"
        json_path = out / "buildroot.json"

        result: dict = {
            "coordinate": f"{group_id}:{artifact_id}:{version}",
            "checks": [],
        }

        # Check generated files exist
        if json_path.exists():
            buildroot_data = json.loads(json_path.read_text())
            inferred_jdk = buildroot_data.get("jdk_version", {}).get("value", "")
        else:
            result["checks"].append({
                "name": "buildroot.json",
                "status": "SKIP",
                "reason": f"File not found: {json_path}",
            })
            inferred_jdk = ""

        # Fetch JAR and read manifest
        manifest_jdk = self._read_jar_build_jdk(group_id, artifact_id, version)

        if manifest_jdk and inferred_jdk:
            match = self._jdk_versions_match(inferred_jdk, manifest_jdk)
            result["checks"].append({
                "name": "jdk_version",
                "status": "MATCH" if match else "MISMATCH",
                "inferred": inferred_jdk,
                "manifest": manifest_jdk,
            })
        elif manifest_jdk:
            result["checks"].append({
                "name": "jdk_version",
                "status": "SKIP",
                "reason": "No inferred JDK version to compare",
                "manifest": manifest_jdk,
            })
        else:
            result["checks"].append({
                "name": "jdk_version",
                "status": "SKIP",
                "reason": "Could not read Build-Jdk-Spec from JAR manifest",
            })

        # Rebuild if requested
        if rebuild and containerfile_path.exists():
            rebuild_result = self._rebuild(containerfile_path)
            result["checks"].append({
                "name": "rebuild",
                **rebuild_result,
            })

        return result

    def inspect(
        self,
        group_id: str,
        artifact_id: str,
        version: str,
    ) -> dict:
        # 1. Fetch + parse POM
        xml_text = fetch_pom(group_id, artifact_id, version, no_cache=self._no_cache)
        pom_parser = PomParser(no_cache=self._no_cache)
        pom_data = pom_parser.parse(xml_text)

        # 2. Resolve parent chain
        chain = pom_parser.resolve_parent_chain(pom_data)
        merged = pom_parser.merge_poms(chain)

        # 3. Resolve properties
        prop_resolver = PropertyResolver()
        resolved_props, prop_gaps = prop_resolver.resolve(merged)

        # 4. Discover CI
        repo_owner, repo_name = None, None
        discovered = discover_repo_from_pom(merged)
        if discovered:
            repo_owner, repo_name = discovered

        ci_data = None
        if repo_owner and repo_name:
            ci_parser = CIParser()
            detected_type, yaml_texts = ci_parser.discover_ci_type(repo_owner, repo_name)
            if yaml_texts:
                if detected_type == "github":
                    ci_data = ci_parser.parse_github_actions(yaml_texts[0])
                elif detected_type == "circleci":
                    ci_data = ci_parser.parse_circleci(yaml_texts[0])

        # 5. Resolve JDK
        jdk_resolver = JdkResolver()
        jdk_spec = jdk_resolver.resolve(
            merged, ci_data, resolved_props,
            group_id=group_id, artifact_id=artifact_id, version=version,
        )

        parent_chain_info = []
        for p in chain:
            parent_chain_info.append({
                "groupId": p.group_id,
                "artifactId": p.artifact_id,
                "version": p.version,
            })

        ci_info = None
        if ci_data:
            ci_info = {
                "ci_type": ci_data.ci_type,
                "java_version": ci_data.java_version.value if ci_data.java_version else None,
                "distribution": ci_data.distribution.value if ci_data.distribution else None,
                "build_commands": ci_data.build_commands,
                "system_packages": ci_data.system_packages,
                "container_images": ci_data.container_images,
                "env_vars": ci_data.env_vars,
            }

        return {
            "coordinate": f"{group_id}:{artifact_id}:{version}",
            "pom_data": {
                "groupId": merged.group_id,
                "artifactId": merged.artifact_id,
                "version": merged.version,
                "packaging": merged.packaging,
                "modules": merged.modules,
            },
            "parent_chain": parent_chain_info,
            "properties": resolved_props,
            "property_gaps": [
                {"field": g.field, "status": g.status, "reason": g.reason}
                for g in prop_gaps
            ],
            "ci_data": ci_info,
            "jdk_spec": {
                "version": jdk_spec.version,
                "distribution": jdk_spec.distribution,
                "base_image": jdk_spec.base_image,
                "source": jdk_spec.source_description,
                "confidence": jdk_spec.confidence.level.value if jdk_spec.confidence else "unknown",
                "conflicts": jdk_spec.conflicts,
            },
            "source_repo": f"https://github.com/{repo_owner}/{repo_name}" if repo_owner else None,
        }

    def _fetch_ci_yamls(
        self, ci_parser: CIParser, repo_owner: str, repo_name: str, ci_type: str
    ) -> list[str]:
        _, yaml_texts = ci_parser.discover_ci_type(repo_owner, repo_name)
        return yaml_texts

    def _enrich_build_commands(
        self, spec: BuildrootSpec, pom_data: PomData
    ) -> None:
        plugin_artifact_ids = {
            p.get("artifactId", "") for p in pom_data.build_plugins
        }

        has_gpg = "maven-gpg-plugin" in plugin_artifact_ids
        has_rat = "apache-rat-plugin" in plugin_artifact_ids or any(
            "rat" in p.get("artifactId", "").lower() for p in pom_data.build_plugins
        )
        is_apache = pom_data.group_id.startswith("org.apache")
        has_wrapper = spec.maven_version != "" or any(
            "./mvnw" in cmd for cmd in spec.build_commands
        )

        if not spec.build_commands:
            base = "./mvnw" if has_wrapper else "mvn"
            cmd = f"{base} clean install -B -DskipTests"
            if has_gpg:
                cmd += " -Dgpg.skip=true"
            if has_rat:
                cmd += " -Drat.skip=true"
            if is_apache:
                cmd += " -Papache-release"
            spec.build_commands = [cmd]
        else:
            enriched = []
            for cmd in spec.build_commands:
                if has_wrapper and cmd.startswith("mvn "):
                    cmd = "./mvnw " + cmd[4:]
                if not _has_flag(cmd, "-DskipTests"):
                    cmd += " -DskipTests"
                if has_gpg and not _has_flag(cmd, "-Dgpg.skip"):
                    cmd += " -Dgpg.skip=true"
                if has_rat and not _has_flag(cmd, "-Drat.skip"):
                    cmd += " -Drat.skip=true"
                if is_apache and not _has_flag(cmd, "-Papache-release"):
                    cmd += " -Papache-release"
                enriched.append(cmd)
            spec.build_commands = enriched

    def _detect_maven_wrapper_version(
        self, repo_owner: str, repo_name: str
    ) -> str:
        content = fetch_maven_wrapper_properties(repo_owner, repo_name)
        if not content:
            return ""
        return _parse_maven_wrapper_version(content)

    def _merge_ci_data(self, target: CIData, source: CIData) -> None:
        if source.java_version and not target.java_version:
            target.java_version = source.java_version
        if source.distribution and not target.distribution:
            target.distribution = source.distribution
        target.build_commands.extend(source.build_commands)
        target.system_packages.extend(source.system_packages)
        target.container_images.extend(source.container_images)
        target.env_vars.update(source.env_vars)

    def _read_jar_build_jdk(
        self, group_id: str, artifact_id: str, version: str
    ) -> str:
        try:
            cached = get_jar_path(group_id, artifact_id, version)
        except (requests.RequestException, ValueError, OSError) as e:
            logger.warning("Could not obtain cached JAR for %s:%s:%s: %s", group_id, artifact_id, version, e)
            return ""

        try:
            with zipfile.ZipFile(cached) as zf:
                manifest_path = "META-INF/MANIFEST.MF"
                if manifest_path not in zf.namelist():
                    return ""
                manifest = zf.read(manifest_path).decode("utf-8", errors="replace")
                for line in manifest.splitlines():
                    if line.startswith("Build-Jdk-Spec:"):
                        return line.split(":", 1)[1].strip()
                    if line.startswith("Build-Jdk:"):
                        raw = line.split(":", 1)[1].strip()
                        parts = raw.split(".")
                        if parts[0] == "1" and len(parts) >= 2:
                            return parts[1]
                        return parts[0]
        except (zipfile.BadZipFile, KeyError):
            logger.warning("Could not read manifest from JAR")
        return ""

    def _jdk_versions_match(self, inferred: str, manifest: str) -> bool:
        def normalize(v: str) -> str:
            v = v.strip()
            if v.startswith("1."):
                return v[2:].split(".")[0]
            return v.split(".")[0]

        return normalize(inferred) == normalize(manifest)

    def _rebuild(self, containerfile_path: Path) -> dict:
        tag = "buildroot-verify:latest"
        cmd = [self._runtime, "build", "-t", tag, "-f", str(containerfile_path), "."]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(containerfile_path.parent),
            )
            if result.returncode == 0:
                return {"status": "SUCCESS", "message": "Container build succeeded"}
            return {
                "status": "FAILURE",
                "message": f"Container build failed (rc={result.returncode})",
                "stderr": result.stderr[:500] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"status": "FAILURE", "message": "Container build timed out (600s)"}
        except FileNotFoundError:
            return {"status": "FAILURE", "message": f"Runtime '{self._runtime}' not found"}
