"""POM fetching and parsing with full parent resolution."""

from __future__ import annotations

import copy
import logging
from typing import Any

import defusedxml.ElementTree as safe_ET
from lxml import etree

from buildroot.pipeline.models import PomData
from buildroot.utils.maven_central import fetch_pom

logger = logging.getLogger(__name__)

MAX_PARENT_DEPTH = 50


def _local_name(tag: str) -> str:
    """Strip namespace from an element tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _is_element(node: etree._Element) -> bool:
    """Check if a node is a real element (not a comment or PI)."""
    return isinstance(node.tag, str)


def _find(element: etree._Element, local: str) -> etree._Element | None:
    """Find first child matching a local name (namespace-agnostic)."""
    for child in element:
        if _is_element(child) and _local_name(child.tag) == local:
            return child
    return None


def _find_all(element: etree._Element, local: str) -> list[etree._Element]:
    """Find all children matching a local name (namespace-agnostic)."""
    return [child for child in element if _is_element(child) and _local_name(child.tag) == local]


def _text(element: etree._Element, local: str) -> str:
    """Get text content of a child element by local name."""
    child = _find(element, local)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _extract_dependency(dep_el: etree._Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("groupId", "artifactId", "version", "scope", "type", "classifier", "optional"):
        val = _text(dep_el, key)
        if val:
            result[key] = val
    exclusions_el = _find(dep_el, "exclusions")
    if exclusions_el is not None:
        excls = []
        for excl in _find_all(exclusions_el, "exclusion"):
            excls.append(f"{_text(excl, 'groupId')}:{_text(excl, 'artifactId')}")
        if excls:
            result["exclusions"] = ",".join(excls)
    return result


def _extract_plugin(plugin_el: etree._Element) -> dict[str, Any]:
    result: dict[str, Any] = {
        "groupId": _text(plugin_el, "groupId") or "org.apache.maven.plugins",
        "artifactId": _text(plugin_el, "artifactId"),
    }
    version = _text(plugin_el, "version")
    if version:
        result["version"] = version

    config_el = _find(plugin_el, "configuration")
    if config_el is not None:
        config: dict[str, str] = {}
        for child in config_el:
            if not _is_element(child):
                continue
            name = _local_name(child.tag)
            if child.text and child.text.strip():
                config[name] = child.text.strip()
        if config:
            result["configuration"] = config

    return result


def _extract_profile(profile_el: etree._Element) -> dict[str, Any]:
    result: dict[str, Any] = {"id": _text(profile_el, "id")}

    activation_el = _find(profile_el, "activation")
    if activation_el is not None:
        activation: dict[str, str] = {}
        for child in activation_el:
            if not _is_element(child):
                continue
            name = _local_name(child.tag)
            if child.text and child.text.strip():
                activation[name] = child.text.strip()
        if activation:
            result["activation"] = activation

    props_el = _find(profile_el, "properties")
    if props_el is not None:
        props = {}
        for child in props_el:
            if not _is_element(child):
                continue
            if child.text:
                props[_local_name(child.tag)] = child.text.strip()
        if props:
            result["properties"] = props

    return result


class PomParser:
    """Parse Maven POM XML and resolve parent chains."""

    def __init__(self, *, no_cache: bool = False):
        self._no_cache = no_cache

    def parse(self, xml_text: str) -> PomData:
        """Parse POM XML text into a PomData model."""
        safe_ET.fromstring(xml_text.encode("utf-8"))

        root = etree.fromstring(xml_text.encode("utf-8"))
        return self._extract_pom_data(root)

    def _extract_pom_data(self, root: etree._Element) -> PomData:
        pom = PomData()

        pom.group_id = _text(root, "groupId")
        pom.artifact_id = _text(root, "artifactId")
        pom.version = _text(root, "version")
        pom.packaging = _text(root, "packaging") or "jar"

        parent_el = _find(root, "parent")
        if parent_el is not None:
            parent_ref = {
                "groupId": _text(parent_el, "groupId"),
                "artifactId": _text(parent_el, "artifactId"),
                "version": _text(parent_el, "version"),
            }
            rel_path = _text(parent_el, "relativePath")
            if rel_path:
                parent_ref["relativePath"] = rel_path
            pom.parent_chain = [parent_ref]

            if not pom.group_id:
                pom.group_id = parent_ref["groupId"]
            if not pom.version:
                pom.version = parent_ref["version"]

        props_el = _find(root, "properties")
        if props_el is not None:
            for child in props_el:
                if not _is_element(child):
                    continue
                if child.text:
                    pom.properties[_local_name(child.tag)] = child.text.strip()

        dep_mgmt_el = _find(root, "dependencyManagement")
        if dep_mgmt_el is not None:
            deps_el = _find(dep_mgmt_el, "dependencies")
            if deps_el is not None:
                for dep in _find_all(deps_el, "dependency"):
                    pom.dependency_management.append(_extract_dependency(dep))

        deps_el = _find(root, "dependencies")
        if deps_el is not None:
            for dep in _find_all(deps_el, "dependency"):
                pom.dependencies.append(_extract_dependency(dep))

        build_el = _find(root, "build")
        if build_el is not None:
            plugins_el = _find(build_el, "plugins")
            if plugins_el is not None:
                for plugin in _find_all(plugins_el, "plugin"):
                    pom.build_plugins.append(_extract_plugin(plugin))

            plugin_mgmt_el = _find(build_el, "pluginManagement")
            if plugin_mgmt_el is not None:
                pm_plugins_el = _find(plugin_mgmt_el, "plugins")
                if pm_plugins_el is not None:
                    for plugin in _find_all(pm_plugins_el, "plugin"):
                        pom.build_plugins.append(_extract_plugin(plugin))

        profiles_el = _find(root, "profiles")
        if profiles_el is not None:
            for profile in _find_all(profiles_el, "profile"):
                pom.profiles.append(_extract_profile(profile))

        modules_el = _find(root, "modules")
        if modules_el is not None:
            for mod in _find_all(modules_el, "module"):
                if mod.text:
                    pom.modules.append(mod.text.strip())

        scm_el = _find(root, "scm")
        if scm_el is not None:
            for key in ("url", "connection", "developerConnection", "tag"):
                val = _text(scm_el, key)
                if val:
                    pom.scm[key] = val

        url_val = _text(root, "url")
        if url_val:
            pom.url = url_val

        return pom

    def resolve_parent_chain(self, pom_data: PomData) -> list[PomData]:
        """Walk the parent chain, fetching each parent POM from Maven Central.

        Returns [child, parent, grandparent, ...].
        """
        chain = [pom_data]
        visited: set[str] = set()
        current = pom_data

        gav_key = f"{current.group_id}:{current.artifact_id}:{current.version}"
        visited.add(gav_key)

        depth = 0
        while current.parent_chain and depth < MAX_PARENT_DEPTH:
            parent_ref = current.parent_chain[0]
            pg = parent_ref.get("groupId", "")
            pa = parent_ref.get("artifactId", "")
            pv = parent_ref.get("version", "")

            if not (pg and pa and pv):
                logger.warning("Incomplete parent reference: %s", parent_ref)
                break

            parent_key = f"{pg}:{pa}:{pv}"
            if parent_key in visited:
                logger.warning("Cycle detected in parent chain: %s", parent_key)
                raise ValueError(f"Cycle detected in parent chain: {parent_key}")

            visited.add(parent_key)
            depth += 1

            try:
                xml_text = fetch_pom(pg, pa, pv, no_cache=self._no_cache)
                parent_pom = self.parse(xml_text)
                chain.append(parent_pom)
                current = parent_pom
            except Exception:
                logger.warning("Failed to fetch parent POM %s", parent_key, exc_info=True)
                break

        return chain

    def merge_poms(self, chain: list[PomData]) -> PomData:
        """Merge a parent chain top-down: child overrides parent.

        chain is [child, parent, grandparent, ...], so we iterate in reverse.
        """
        if not chain:
            return PomData()
        if len(chain) == 1:
            return copy.deepcopy(chain[0])

        reversed_chain = list(reversed(chain))
        merged = copy.deepcopy(reversed_chain[0])

        for pom in reversed_chain[1:]:
            if pom.group_id:
                merged.group_id = pom.group_id
            if pom.artifact_id:
                merged.artifact_id = pom.artifact_id
            if pom.version:
                merged.version = pom.version
            if pom.packaging != "jar":
                merged.packaging = pom.packaging

            merged.properties.update(pom.properties)

            existing_dm = {
                f"{d['groupId']}:{d['artifactId']}": d
                for d in merged.dependency_management
            }
            for dep in pom.dependency_management:
                key = f"{dep.get('groupId', '')}:{dep.get('artifactId', '')}"
                existing_dm[key] = dep
            merged.dependency_management = list(existing_dm.values())

            existing_plugins = {
                f"{p['groupId']}:{p['artifactId']}": p
                for p in merged.build_plugins
            }
            for plugin in pom.build_plugins:
                key = f"{plugin['groupId']}:{plugin['artifactId']}"
                existing_plugins[key] = plugin
            merged.build_plugins = list(existing_plugins.values())

            if pom.dependencies:
                merged.dependencies = pom.dependencies

            if pom.modules:
                merged.modules = pom.modules

            if pom.profiles:
                merged.profiles = pom.profiles

            if pom.scm:
                merged.scm.update(pom.scm)
            if pom.url:
                merged.url = pom.url

        full_chain_refs = []
        for p in chain:
            full_chain_refs.append({
                "groupId": p.group_id,
                "artifactId": p.artifact_id,
                "version": p.version,
            })
        merged.parent_chain = full_chain_refs

        return merged
