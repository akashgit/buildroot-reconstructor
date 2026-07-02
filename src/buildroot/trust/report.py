"""Human-readable Markdown trust report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from buildroot import __version__
from buildroot.pipeline.models import BuildrootSpec
from buildroot.trust.delta import DeltaReport


_TIER_DESCRIPTIONS = {
    1: "Tier 1 — SLSA L3 provenance, cryptographically signed, SBOM attested",
    2: "Tier 2 — Signed binaries with GPG/checksum verification",
    3: "Tier 3 — Archive/unverified source, no provenance guarantees",
}

_FILE_TABLE = [
    ("Containerfile", "Root-level Containerfile (exact variant, default)"),
    ("buildroot.json", "Machine-readable build environment specification"),
    ("exact/Containerfile", "Containerfile using the original (exact) JDK source"),
    ("exact/buildroot.json", "Build spec for the exact variant"),
    ("exact/sbom.cdx.json", "CycloneDX SBOM for the exact variant"),
    ("trusted/Containerfile", "Containerfile using a trusted-source JDK"),
    ("trusted/buildroot.json", "Build spec for the trusted variant"),
    ("trusted/sbom.cdx.json", "CycloneDX SBOM for the trusted variant"),
    ("delta_report.json", "JSON comparison of exact vs trusted variants"),
]


def generate_trust_report(
    spec: BuildrootSpec,
    delta: DeltaReport,
    output_dir: Path,
) -> Path:
    """Generate a comprehensive Markdown trust report.

    Returns the path to the written trust_report.md file.
    """
    coordinate = delta.coordinate or _coordinate_from_spec(spec)
    sections = [
        _header(coordinate),
        _executive_summary(coordinate, delta, spec),
        _how_to_use(output_dir),
        _trust_assessment(spec, delta),
        _variant_comparison(delta),
        _gaps_and_risks(spec),
        _security_checklist(spec, delta),
        _next_steps(coordinate, delta),
    ]

    content = "\n".join(sections)
    report_path = output_dir / "trust_report.md"
    report_path.write_text(content)
    return report_path


def _coordinate_from_spec(spec: BuildrootSpec) -> str:
    p = spec.pom_data
    if p.group_id and p.artifact_id and p.version:
        return f"{p.group_id}:{p.artifact_id}:{p.version}"
    return "unknown"


def _header(coordinate: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"# Trust Report: {coordinate}\n"
        f"\n"
        f"- **Generated**: {ts}\n"
        f"- **buildroot-reconstructor**: v{__version__}\n"
    )


def _executive_summary(
    coordinate: str, delta: DeltaReport, spec: BuildrootSpec
) -> str:
    rec = delta.recommendation or "investigate"
    equiv = delta.functional_equivalence or "NOT_EVALUATED"
    tier = spec.provenance_tier or delta.trusted.provenance_tier

    if rec == "use_trusted":
        posture = "The trusted variant is recommended for production use."
    elif rec == "use_exact":
        posture = "The exact variant should be used — the trusted variant diverges."
    elif rec == "either":
        posture = "Both variants are functionally equivalent; either may be used."
    else:
        posture = "Further investigation is needed before choosing a variant."

    tier_label = f"Tier {tier}" if tier else "unassessed"

    return (
        f"## Executive Summary\n"
        f"\n"
        f"Analyzed **{coordinate}** with dual-variant reconstruction. "
        f"Functional equivalence verdict: **{equiv}**. "
        f"Trust posture: {tier_label}. "
        f"{posture}\n"
        f"\n"
        f"**Recommendation**: `{rec}`\n"
    )


def _how_to_use(output_dir: Path) -> str:
    lines = [
        "## How to Use These Outputs",
        "",
        "### Generated Files",
        "",
        "| File | Description |",
        "|------|-------------|",
    ]
    for fname, desc in _FILE_TABLE:
        lines.append(f"| `{fname}` | {desc} |")

    lines += [
        "",
        "### Building the Trusted Variant",
        "",
        "```bash",
        f"cd {output_dir}",
        "podman build -f trusted/Containerfile .",
        "```",
        "",
        "### Building the Exact Variant",
        "",
        "```bash",
        f"cd {output_dir}",
        "podman build -f exact/Containerfile .",
        "```",
        "",
        "### Reading the Delta Report",
        "",
        "The `delta_report.json` file contains a machine-readable comparison of "
        "the two variants. Key fields:",
        "",
        "- `version_diff` — fields that differ between variants (JDK version, base image, source)",
        "- `functional_equivalence` — verdict: IDENTICAL, EQUIVALENT, DIVERGENT, or NOT_EVALUATED",
        "- `recommendation` — suggested action: use_trusted, use_exact, either, or investigate",
        "",
        "### Consuming CycloneDX SBOMs",
        "",
        "The `sbom.cdx.json` files in each variant directory are CycloneDX 1.5 SBOMs. "
        "Use them with standard tools:",
        "",
        "```bash",
        "# Scan for known vulnerabilities",
        "grype sbom:exact/sbom.cdx.json",
        "",
        "# Inspect components",
        "syft convert exact/sbom.cdx.json -o table",
        "",
        "# Validate SBOM schema",
        "bomctl validate exact/sbom.cdx.json",
        "```",
    ]
    return "\n".join(lines) + "\n"


def _trust_assessment(spec: BuildrootSpec, delta: DeltaReport) -> str:
    tier = spec.provenance_tier or delta.trusted.provenance_tier
    provider = spec.provenance_provider or delta.trusted.jdk_source or "unknown"
    verification = spec.provenance_verification or []
    if not verification and tier is not None:
        from buildroot.trust.registry import DEFAULT_SOURCES
        for src in DEFAULT_SOURCES:
            if src.provider == provider:
                verification = src.verification
                break

    lines = [
        "## Trust Assessment",
        "",
        "### Source Tier",
        "",
        f"**{_TIER_DESCRIPTIONS.get(tier, f'Tier {tier}') if tier else 'No tier assigned'}**",
        "",
    ]

    lines += [
        "### Provider Details",
        "",
        f"- **Provider**: {provider}",
        f"- **Verification methods**: {', '.join(verification) if verification else 'none'}",
    ]

    if any(s == "gpg" for s in verification):
        lines.append("- **GPG signed**: yes")
    if any(s == "checksum" for s in verification):
        lines.append("- **Checksum verified**: yes")
    if any(s == "sbom" for s in verification):
        lines.append("- **SBOM attested**: yes")

    slsa = None
    if delta.trusted.provenance_tier is not None:
        from buildroot.trust.registry import DEFAULT_SOURCES
        for src in DEFAULT_SOURCES:
            if src.provider == provider and src.slsa_level is not None:
                slsa = src.slsa_level
                break
    if slsa is not None:
        lines.append(f"- **SLSA level**: L{slsa}")

    lines += [
        "",
        "### JDK Resolution",
        "",
        f"- **Requested version**: {spec.jdk_requested_version or spec.jdk_spec.version or 'unknown'}",
        f"- **Resolved version**: {spec.jdk_spec.version or 'unknown'}",
        f"- **Resolution type**: {spec.jdk_resolution_type or 'unknown'}",
    ]

    if spec.jdk_resolution_type == "substituted":
        lines.append(
            f"- **Substitution reason**: JDK {spec.jdk_requested_version} not available from "
            f"trusted sources; substituted with JDK {spec.jdk_spec.version}"
        )

    lines += [
        "",
        "### Base Image Provenance",
        "",
        f"- **Exact variant**: `{delta.exact.base_image or spec.base_image or 'unknown'}`",
        f"- **Trusted variant**: `{delta.trusted.base_image or spec.trusted_base_image or 'unknown'}`",
    ]

    return "\n".join(lines) + "\n"


def _variant_comparison(delta: DeltaReport) -> str:
    lines = [
        "## Variant Comparison",
        "",
    ]
    md = delta.to_markdown()
    for line in md.splitlines():
        if line.startswith("# Delta Report:"):
            continue
        lines.append(line)

    if (delta.functional_equivalence or "NOT_EVALUATED") == "NOT_EVALUATED":
        lines += [
            "",
            "> **Note**: Functional equivalence has not been evaluated yet. "
            "Run `buildroot agent <coordinate>` to perform a full build comparison.",
        ]

    return "\n".join(lines) + "\n"


def _gaps_and_risks(spec: BuildrootSpec) -> str:
    lines = [
        "## Gaps & Risks",
        "",
    ]

    entries = spec.gaps.entries if spec.gaps else []
    if entries:
        lines += [
            "### Detected Gaps",
            "",
            "| Field | Status | Reason |",
            "|-------|--------|--------|",
        ]
        for e in entries:
            lines.append(f"| {e.field} | {e.status} | {e.reason} |")
        lines.append("")

        lines.append("### Risk Assessment")
        lines.append("")
        for e in entries:
            risk = _risk_for_gap(e.field, e.status)
            lines.append(f"- **{e.field}** ({e.status}): {risk}")
        lines.append("")
    else:
        lines += [
            "No gaps detected.",
            "",
        ]

    if spec.jdk_resolution_type == "substituted":
        lines += [
            "### JDK Substitution Risks",
            "",
            f"- JDK {spec.jdk_requested_version} substituted with JDK {spec.jdk_spec.version} "
            f"— API compatibility risk: newer JDK may include API changes that affect build output",
            f"- Bytecode target level may differ — verify `-target` / `--release` compiler flags",
            "",
        ]

    return "\n".join(lines) + "\n"


def _risk_for_gap(field: str, status: str) -> str:
    risk_map = {
        "java_version": "JDK version inferred — may not match exact build requirements",
        "distribution": "JDK distribution inferred — binary-level differences possible",
        "build_commands": "Build commands inferred — may miss project-specific flags or profiles",
        "maven_version": "Maven version unknown — build behavior may differ across versions",
        "source_repo": "Source repository not confirmed — provenance chain incomplete",
        "git_tag": "Git tag inferred — may not match the exact release commit",
    }
    return risk_map.get(field, f"Field '{field}' has status '{status}' — review manually")


def _security_checklist(spec: BuildrootSpec, delta: DeltaReport) -> str:
    verification = spec.provenance_verification or []
    tier = spec.provenance_tier

    lines = [
        "## Security Review Checklist",
        "",
    ]

    items = [
        ("Verify base image digest matches expected", None),
        ("Review provenance tier and verification methods", None),
        ("Check SBOM components against known CVE databases", None),
        ("Verify source repository URL is legitimate", None),
        ("Review build commands for injection risks", None),
        ("Compare exact vs trusted variants for unexpected divergence", None),
        ("Validate CycloneDX SBOM schema compliance", None),
    ]

    for label, _ in items:
        lines.append(f"- [ ] {label}")

    lines.append("")

    notes = []
    if tier == 1 and "gpg" in verification:
        notes.append("GPG verification is already in place (Tier 1 source).")
    if tier == 1 and "checksum" in verification:
        notes.append("Checksum verification is already in place (Tier 1 source).")
    if "sbom" in verification:
        notes.append("SBOM attestation is provided by the source.")

    if notes:
        lines.append("**Automatically satisfied**:")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _next_steps(coordinate: str, delta: DeltaReport) -> str:
    rec = delta.recommendation or "investigate"
    equiv = delta.functional_equivalence or "NOT_EVALUATED"

    lines = [
        "## Next Steps",
        "",
    ]

    if equiv == "NOT_EVALUATED":
        lines += [
            f"1. Run `buildroot agent {coordinate}` to perform a full build comparison "
            "and evaluate functional equivalence between variants.",
            "2. Re-run `buildroot reconstruct` after the agent comparison to get "
            "an updated trust report with a definitive recommendation.",
        ]
    elif equiv == "DIVERGENT":
        classes = delta.classes_divergent
        lines.append(
            "The exact and trusted variants produce **divergent** output. "
            "Investigate the following:"
        )
        lines.append("")
        if classes:
            lines.append(
                f"1. Review the {len(classes)} divergent class(es): "
                f"{', '.join(classes[:5])}"
                + (" ..." if len(classes) > 5 else "")
            )
        else:
            lines.append("1. Review the variant comparison above for specific differences.")
        lines.append("2. Check whether divergence is cosmetic (timestamps, ordering) or semantic.")
        lines.append(
            "3. If cosmetic, consider adding metadata-strip patterns and rebuilding."
        )
    elif rec in ("use_trusted", "either"):
        lines += [
            "The trusted variant is functionally equivalent to the exact variant "
            "and has verified provenance.",
            "",
            "1. Use `trusted/Containerfile` for production builds.",
            "2. Integrate `trusted/sbom.cdx.json` into your vulnerability scanning pipeline.",
            "3. Archive `delta_report.json` as part of your supply chain audit trail.",
        ]
    elif rec == "use_exact":
        lines += [
            "The exact variant is recommended.",
            "",
            "1. Use `exact/Containerfile` for production builds.",
            "2. Investigate whether a trusted-source JDK can be configured to reduce divergence.",
        ]
    else:
        lines += [
            f"1. Review the variant comparison and gap analysis above.",
            f"2. Run `buildroot agent {coordinate}` for deeper analysis if needed.",
        ]

    lines.append("")
    return "\n".join(lines) + "\n"
