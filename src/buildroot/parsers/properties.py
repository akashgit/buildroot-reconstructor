"""Maven property placeholder resolution."""

from __future__ import annotations

import logging
import re

from buildroot.pipeline.models import GapEntry, PomData, Source

logger = logging.getLogger(__name__)

MAX_RECURSION_DEPTH = 10
PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)}")

CI_FRIENDLY_PROPS = {"revision", "sha1", "changelist"}

PROJECT_PROPS = {"project.groupId", "project.artifactId", "project.version",
                 "project.name", "project.description", "project.packaging",
                 "pom.groupId", "pom.artifactId", "pom.version"}


class PropertyResolver:
    """Resolve ${...} placeholders in a merged POM's property map."""

    def resolve(self, merged_pom: PomData) -> tuple[dict[str, str], list[GapEntry]]:
        """Resolve all properties, returning (resolved_map, gaps)."""
        prop_map = dict(merged_pom.properties)
        gaps: list[GapEntry] = []

        self._inject_project_props(prop_map, merged_pom)

        resolved: dict[str, str] = {}
        for key, value in prop_map.items():
            resolved_val, entry_gaps = self._resolve_value(key, value, prop_map)
            resolved[key] = resolved_val
            gaps.extend(entry_gaps)

        return resolved, gaps

    def _inject_project_props(self, prop_map: dict[str, str], pom: PomData) -> None:
        mapping = {
            "project.groupId": pom.group_id,
            "project.artifactId": pom.artifact_id,
            "project.version": pom.version,
            "project.packaging": pom.packaging,
            "pom.groupId": pom.group_id,
            "pom.artifactId": pom.artifact_id,
            "pom.version": pom.version,
        }
        for key, value in mapping.items():
            if value and key not in prop_map:
                prop_map[key] = value

    def _resolve_value(
        self,
        original_key: str,
        value: str,
        prop_map: dict[str, str],
    ) -> tuple[str, list[GapEntry]]:
        gaps: list[GapEntry] = []
        visited: set[str] = set()
        return self._resolve_recursive(original_key, value, prop_map, gaps, visited, 0)

    def _resolve_recursive(
        self,
        context_key: str,
        value: str,
        prop_map: dict[str, str],
        gaps: list[GapEntry],
        visited: set[str],
        depth: int,
    ) -> tuple[str, list[GapEntry]]:
        if depth >= MAX_RECURSION_DEPTH:
            gaps.append(GapEntry(
                field=context_key,
                status="unresolved",
                reason=f"Max recursion depth ({MAX_RECURSION_DEPTH}) exceeded",
                source=Source.DEFAULTED,
            ))
            return value, gaps

        def replace_match(m: re.Match) -> str:
            ref = m.group(1)

            if ref in CI_FRIENDLY_PROPS:
                gaps.append(GapEntry(
                    field=ref,
                    status="unresolved",
                    reason=f"CI-friendly version placeholder ${{{ref}}} is set via -D in CI, not resolvable from POM",
                    source=Source.DEFAULTED,
                ))
                return m.group(0)

            if ref.startswith("env."):
                gaps.append(GapEntry(
                    field=ref,
                    status="unresolved",
                    reason=f"Environment variable ${{{ref}}} not available from POM",
                    source=Source.DEFAULTED,
                ))
                return m.group(0)

            if ref.startswith("settings."):
                gaps.append(GapEntry(
                    field=ref,
                    status="unresolved",
                    reason=f"Settings property ${{{ref}}} not available from POM",
                    source=Source.DEFAULTED,
                ))
                return m.group(0)

            if ref in visited:
                gaps.append(GapEntry(
                    field=ref,
                    status="unresolved",
                    reason=f"Cycle detected: ${{{ref}}} references itself through chain",
                    source=Source.DEFAULTED,
                ))
                return m.group(0)

            if ref in prop_map:
                visited.add(ref)
                resolved, _ = self._resolve_recursive(
                    context_key, prop_map[ref], prop_map, gaps, visited, depth + 1
                )
                visited.discard(ref)
                return resolved

            if ref.startswith("project.") or ref.startswith("pom."):
                gaps.append(GapEntry(
                    field=ref,
                    status="unresolved",
                    reason=f"Project property ${{{ref}}} not found in POM",
                    source=Source.DEFAULTED,
                ))
                return m.group(0)

            gaps.append(GapEntry(
                field=ref,
                status="unresolved",
                reason=f"Property ${{{ref}}} not defined in POM or parent chain",
                source=Source.DEFAULTED,
            ))
            return m.group(0)

        result = PLACEHOLDER_RE.sub(replace_match, value)
        return result, gaps
