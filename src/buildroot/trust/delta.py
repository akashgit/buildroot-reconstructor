"""Delta report generation for dual-variant build comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from buildroot.utils.jar_comparator import ComparisonReport


@dataclass
class VariantResult:
    """Result from generating one variant (exact or trusted)."""

    name: str  # "exact" | "trusted"
    containerfile_path: Path = field(default_factory=lambda: Path())
    buildroot_json_path: Path = field(default_factory=lambda: Path())
    base_image: str = ""
    jdk_version: str = ""
    jdk_source: str = ""
    provenance_tier: int | None = None


@dataclass
class DeltaReport:
    """Comparison report between exact and trusted build variants."""

    coordinate: str = ""
    exact: VariantResult = field(default_factory=lambda: VariantResult(name="exact"))
    trusted: VariantResult = field(
        default_factory=lambda: VariantResult(name="trusted")
    )
    version_diff: dict[str, tuple[str, str]] = field(default_factory=dict)
    structural_match: bool | None = None
    metadata_match: bool | None = None
    bytecode_match: bool | None = None
    manifest_diff_keys: list[str] = field(default_factory=list)
    classes_divergent: list[str] = field(default_factory=list)
    exact_reward: float = 0.0
    trusted_reward: float = 0.0
    reward_delta: float = 0.0
    functional_equivalence: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "exact": {
                "name": self.exact.name,
                "containerfile_path": str(self.exact.containerfile_path),
                "buildroot_json_path": str(self.exact.buildroot_json_path),
                "base_image": self.exact.base_image,
                "jdk_version": self.exact.jdk_version,
                "jdk_source": self.exact.jdk_source,
                "provenance_tier": self.exact.provenance_tier,
            },
            "trusted": {
                "name": self.trusted.name,
                "containerfile_path": str(self.trusted.containerfile_path),
                "buildroot_json_path": str(self.trusted.buildroot_json_path),
                "base_image": self.trusted.base_image,
                "jdk_version": self.trusted.jdk_version,
                "jdk_source": self.trusted.jdk_source,
                "provenance_tier": self.trusted.provenance_tier,
            },
            "version_diff": {
                k: list(v) for k, v in self.version_diff.items()
            },
            "structural_match": self.structural_match,
            "metadata_match": self.metadata_match,
            "bytecode_match": self.bytecode_match,
            "manifest_diff_keys": self.manifest_diff_keys,
            "classes_divergent": self.classes_divergent,
            "exact_reward": self.exact_reward,
            "trusted_reward": self.trusted_reward,
            "reward_delta": self.reward_delta,
            "functional_equivalence": self.functional_equivalence,
            "recommendation": self.recommendation,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Delta Report: {self.coordinate}",
            "",
            "## Variant Comparison",
            "",
            "| Field | Exact | Trusted |",
            "|-------|-------|---------|",
            f"| JDK Version | {self.exact.jdk_version} | {self.trusted.jdk_version} |",
            f"| Base Image | {self.exact.base_image} | {self.trusted.base_image} |",
            f"| JDK Source | {self.exact.jdk_source} | {self.trusted.jdk_source} |",
            f"| Provenance Tier | {self.exact.provenance_tier or 'N/A'} | {self.trusted.provenance_tier or 'N/A'} |",
            "",
        ]

        if self.version_diff:
            lines.append("## Version Differences")
            lines.append("")
            for field_name, (exact_val, trusted_val) in self.version_diff.items():
                lines.append(f"- **{field_name}**: `{exact_val}` -> `{trusted_val}`")
            lines.append("")

        lines.append("## Functional Equivalence")
        lines.append("")
        lines.append(f"**Verdict**: {self.functional_equivalence or 'NOT_EVALUATED'}")
        lines.append("")

        if self.structural_match is not None:
            lines.append(f"- Structural match: {'Yes' if self.structural_match else 'No'}")
        if self.metadata_match is not None:
            lines.append(f"- Metadata match: {'Yes' if self.metadata_match else 'No'}")
        if self.bytecode_match is not None:
            lines.append(f"- Bytecode match: {'Yes' if self.bytecode_match else 'No'}")
        if self.manifest_diff_keys:
            lines.append(f"- Manifest diff keys: {', '.join(self.manifest_diff_keys)}")
        if self.classes_divergent:
            lines.append(f"- Divergent classes: {len(self.classes_divergent)}")
        lines.append("")

        lines.append("## Recommendation")
        lines.append("")
        lines.append(f"**{self.recommendation or 'investigate'}**")
        lines.append("")

        return "\n".join(lines)


def build_delta_report(
    exact: VariantResult,
    trusted: VariantResult,
    comparison: ComparisonReport | None = None,
) -> DeltaReport:
    report = DeltaReport(exact=exact, trusted=trusted)

    diffs: dict[str, tuple[str, str]] = {}
    if exact.jdk_version != trusted.jdk_version:
        diffs["jdk_version"] = (exact.jdk_version, trusted.jdk_version)
    if exact.base_image != trusted.base_image:
        diffs["base_image"] = (exact.base_image, trusted.base_image)
    if exact.jdk_source != trusted.jdk_source:
        diffs["jdk_source"] = (exact.jdk_source, trusted.jdk_source)
    report.version_diff = diffs

    if comparison is not None:
        report.structural_match = comparison.structural.match
        report.metadata_match = comparison.metadata.match
        report.bytecode_match = comparison.bytecode.match
        report.manifest_diff_keys = list(comparison.metadata.manifest_diff_keys)
        report.classes_divergent = list(comparison.bytecode.classes_divergent)

        verdict = comparison.verdict
        if verdict == "IDENTICAL":
            report.functional_equivalence = "IDENTICAL"
        elif verdict == "EQUIVALENT":
            report.functional_equivalence = "EQUIVALENT"
        elif verdict == "DIVERGENT":
            report.functional_equivalence = "DIVERGENT"
        elif verdict == "FAILED":
            report.functional_equivalence = "FAILED"
        else:
            report.functional_equivalence = "NOT_EVALUATED"
    else:
        report.functional_equivalence = "NOT_EVALUATED"

    has_trusted_provenance = trusted.provenance_tier is not None

    if report.functional_equivalence == "IDENTICAL":
        report.recommendation = "use_trusted" if has_trusted_provenance else "either"
    elif report.functional_equivalence == "EQUIVALENT":
        report.recommendation = "use_trusted" if has_trusted_provenance else "either"
    elif report.functional_equivalence == "DIVERGENT":
        report.recommendation = "use_exact"
    elif report.functional_equivalence == "FAILED":
        report.recommendation = "investigate"
    else:
        report.recommendation = "investigate"

    return report
