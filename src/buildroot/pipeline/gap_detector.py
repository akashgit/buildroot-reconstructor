"""Gap detection and confidence reporting for buildroot reconstruction."""

from __future__ import annotations

import logging

from buildroot.generators.containerfile import DEFAULT_BUILD_COMMAND, RUNNER_IMAGE_MAP
from buildroot.pipeline.models import BuildrootSpec, GapEntry, GapReport, Source

logger = logging.getLogger(__name__)


class GapDetector:
    """Analyze a BuildrootSpec and produce a gap report with confidence levels."""

    def analyze(self, spec: BuildrootSpec) -> GapReport:
        entries: list[GapEntry] = []

        self._check_jdk_confidence(spec, entries)
        self._check_ubuntu_latest(spec, entries)
        self._check_unresolved_properties(spec, entries)
        self._check_maven_wrapper(spec, entries)
        self._check_build_command(spec, entries)
        self._check_system_packages(spec, entries)

        report = GapReport(entries=entries)
        return report

    def format_human_readable(self, report: GapReport) -> str:
        if not report.entries:
            return "No gaps detected. All fields have high confidence.\n"

        lines = []
        lines.append("=" * 60)
        lines.append("  GAP REPORT")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"  {'Field':<30} {'Status':<12} {'Source':<10}")
        lines.append(f"  {'-'*30} {'-'*12} {'-'*10}")

        for entry in report.entries:
            lines.append(
                f"  {entry.field:<30} {entry.status:<12} {entry.source.value:<10}"
            )
            lines.append(f"    -> {entry.reason}")

        lines.append("")
        summary = self._compute_summary(report)
        lines.append(f"  Confidence: {summary}")
        lines.append("=" * 60)
        return "\n".join(lines) + "\n"

    def format_machine_readable(self, report: GapReport) -> dict:
        entries = []
        for entry in report.entries:
            entries.append({
                "field": entry.field,
                "status": entry.status,
                "reason": entry.reason,
                "source": entry.source.value,
            })

        return {
            "entries": entries,
            "overall_confidence": self.compute_overall_confidence(report),
            "summary": self._compute_summary(report),
        }

    def compute_overall_confidence(self, report: GapReport) -> str:
        if not report.entries:
            return "HIGH"

        sources = [e.source for e in report.entries]
        defaulted_count = sum(1 for s in sources if s == Source.DEFAULTED)
        inferred_count = sum(1 for s in sources if s == Source.INFERRED)
        total = len(sources)

        if defaulted_count > total / 2:
            return "LOW"
        if defaulted_count > 0 or inferred_count > 0:
            return "MEDIUM"
        return "HIGH"

    def _compute_summary(self, report: GapReport) -> str:
        if not report.entries:
            return "all fields observed"

        sources = [e.source for e in report.entries]
        observed = sum(1 for s in sources if s == Source.OBSERVED)
        inferred = sum(1 for s in sources if s == Source.INFERRED)
        defaulted = sum(1 for s in sources if s == Source.DEFAULTED)

        parts = []
        if observed:
            parts.append(f"{observed} observed")
        if inferred:
            parts.append(f"{inferred} inferred")
        if defaulted:
            parts.append(f"{defaulted} defaulted")
        return ", ".join(parts)

    def _check_jdk_confidence(
        self, spec: BuildrootSpec, entries: list[GapEntry]
    ) -> None:
        jdk = spec.jdk_spec
        if not jdk.confidence:
            entries.append(GapEntry(
                field="jdk_version",
                status="missing",
                reason="No confidence data for JDK version",
                source=Source.DEFAULTED,
            ))
            return

        if jdk.confidence.level == Source.DEFAULTED:
            entries.append(GapEntry(
                field="jdk_version",
                status="defaulted",
                reason=jdk.confidence.reason,
                source=Source.DEFAULTED,
            ))
        elif jdk.confidence.level == Source.INFERRED:
            entries.append(GapEntry(
                field="jdk_version",
                status="inferred",
                reason=jdk.confidence.reason,
                source=Source.INFERRED,
            ))

    def _check_ubuntu_latest(
        self, spec: BuildrootSpec, entries: list[GapEntry]
    ) -> None:
        if not spec.ci_data:
            return
        runner_os = spec.ci_data.runner_os
        if runner_os == "ubuntu-latest":
            mapped = RUNNER_IMAGE_MAP.get("ubuntu-latest", "24.04")
            entries.append(GapEntry(
                field="runner_os",
                status="mapped",
                reason=(
                    f"ubuntu-latest mapped to ubuntu:{mapped}; "
                    "this mapping may become stale"
                ),
                source=Source.INFERRED,
            ))

    def _check_unresolved_properties(
        self, spec: BuildrootSpec, entries: list[GapEntry]
    ) -> None:
        props = spec.pom_data.properties
        for key, value in props.items():
            if "${" in str(value):
                entries.append(GapEntry(
                    field=f"property:{key}",
                    status="unresolved",
                    reason=f"Property {key} still contains placeholder: {value}",
                    source=Source.DEFAULTED,
                ))

    def _check_maven_wrapper(
        self, spec: BuildrootSpec, entries: list[GapEntry]
    ) -> None:
        if not spec.maven_version:
            entries.append(GapEntry(
                field="maven_version",
                status="defaulted",
                reason=(
                    "No Maven wrapper or explicit version found; "
                    "using system default"
                ),
                source=Source.DEFAULTED,
            ))

    def _check_build_command(
        self, spec: BuildrootSpec, entries: list[GapEntry]
    ) -> None:
        if not spec.build_commands:
            entries.append(GapEntry(
                field="build_command",
                status="defaulted",
                reason=(
                    f"No build command found in CI; "
                    f"defaulting to '{DEFAULT_BUILD_COMMAND}'"
                ),
                source=Source.DEFAULTED,
            ))

    def _check_system_packages(
        self, spec: BuildrootSpec, entries: list[GapEntry]
    ) -> None:
        if not spec.ci_data:
            entries.append(GapEntry(
                field="system_packages",
                status="unknown",
                reason="No CI data available to detect system packages",
                source=Source.DEFAULTED,
            ))
