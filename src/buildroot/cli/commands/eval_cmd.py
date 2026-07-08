"""CLI command for standalone Containerfile evaluation."""

from __future__ import annotations

import json
import sys

import click


@click.command("eval")
@click.argument("containerfile", type=click.Path(exists=True))
@click.argument("coordinate")
@click.option("--host", default=None, help="SSH host for remote builds (default: run locally)")
@click.option("--timeout", default=900, type=int, help="Build timeout in seconds")
@click.option("--pretty/--no-pretty", default=True, help="Pretty-print JSON output")
@click.option(
    "--report",
    type=click.Choice(["json", "markdown", "both", "none"]),
    default="none",
    help="Report format (json, markdown, both, or none)",
)
@click.option("--no-cache", is_flag=True, help="Disable podman layer caching (rebuild all layers)")
@click.option("--trusted", is_flag=True, default=False,
              help="Enforce trusted-source-only constraint (L1.5 gate)")
@click.option("--jdk-version", default="", help="Expected JDK version for fallback bytecode check")
@click.option("--no-isolate-podman", is_flag=True, default=False, help="Disable podman storage isolation")
@click.option("--pnc-mode", is_flag=True, default=False, help="PNC-aware JAR comparison (filter redhat version-alignment diffs)")
def eval_cmd(containerfile, coordinate, host, timeout, pretty, report, no_cache, trusted, jdk_version, no_isolate_podman, pnc_mode):
    """Evaluate a Containerfile against a Maven Central artifact.

    Returns JSON with L1-L4 scores, comparison report, and reward.
    Builds run locally via podman by default; pass --host to use a remote SSH host.

    \b
    Examples:
        buildroot eval Containerfile org.apache.commons:commons-lang3:3.14.0
        buildroot eval my.Containerfile com.fasterxml.jackson.core:jackson-core:2.16.1 --host myserver
        buildroot eval Containerfile org.example:lib:1.0 --trusted
    """
    from pathlib import Path

    from buildroot.agent.evaluator import Evaluator

    cf_text = Path(containerfile).read_text()
    capture_full_log = report != "none"
    isolate_podman = not no_isolate_podman
    evaluator = Evaluator(host=host, timeout=timeout, no_cache=no_cache, isolate_podman=isolate_podman)
    result = evaluator.evaluate(cf_text, coordinate, capture_full_log=capture_full_log, trusted=trusted, jdk_version=jdk_version, pnc_mode=pnc_mode)

    if report != "none":
        from buildroot.eval.audit import build_audit_log, extract_dynamic_assets, extract_static_assets
        from buildroot.eval.report import build_report

        static = extract_static_assets(cf_text)
        dynamic = extract_dynamic_assets(result.build_log)

        from buildroot.utils.maven_central import MAVEN_CENTRAL_BASE

        group_id, artifact_id, version = coordinate.split(":")
        group_path = group_id.replace(".", "/")
        ref_url = (
            f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/{version}/"
            f"{artifact_id}-{version}.jar"
        )
        audit_log = build_audit_log(static, dynamic, reference_jar_url=ref_url)

        full_report = build_report(result, cf_text, coordinate, audit_log)

        safe_coord = coordinate.replace(":", "_")
        results_dir = Path("results") / safe_coord
        results_dir.mkdir(parents=True, exist_ok=True)

        if report in ("json", "both"):
            (results_dir / "report.json").write_text(full_report.to_json())
            click.echo(f"Report written to {results_dir / 'report.json'}", err=True)

        if report in ("markdown", "both"):
            (results_dir / "report.md").write_text(full_report.to_markdown())
            click.echo(f"Report written to {results_dir / 'report.md'}", err=True)

    output = {
        "l1_parse": result.l1_parse,
        "l2_build": result.l2_build,
        "l3_command": result.l3_command,
        "l4_match": result.l4_match,
        "l4_score": round(result.l4_score, 4),
        "reward": round(result.reward, 4),
        "level_reached": result.level_reached,
        "comparison_verdict": result.comparison_verdict,
        "error_summary": result.error_summary or None,
        "diff_summary": getattr(result, "diff_summary", None),
    }

    if result.l4_signal_source:
        output["l4_signal_source"] = result.l4_signal_source
    if result.l4_signal_source == "fallback_signals":
        output["fallback_signals"] = {
            "bytecode_version_match": result.bytecode_version_match,
            "manifest_sanity": result.manifest_sanity,
            "unit_tests_pass": result.unit_tests_pass,
            "structural_match": result.structural_match,
        }

    if result.trust_check or result.trust_violations:
        output["trust_check"] = result.trust_check
        output["trust_violations"] = result.trust_violations

    if result.advisory_findings:
        output["advisory_findings"] = [f.to_dict() for f in result.advisory_findings]
        output["pinning_status"] = result.pinning_status

    if hasattr(result, "comparison_report") and result.comparison_report:
        cr = result.comparison_report
        output["comparison_report"] = {
            "verdict": cr.verdict,
            "equivalence_score": round(cr.equivalence_score(), 4),
            "structural_match": cr.structural.match,
            "metadata_match": cr.metadata.match,
            "bytecode_match": cr.bytecode.match,
        }

    if result.test_result is not None:
        output["test_result"] = result.test_result.to_dict()

    indent = 2 if pretty else None
    click.echo(json.dumps(output, indent=indent))
    if pretty and result.advisory_findings:
        status = result.pinning_status
        counts = status["counts"]
        parts = []
        for sev in ("error", "warning", "info"):
            if counts[sev]:
                parts.append(f"{counts[sev]} {sev}{'s' if counts[sev] > 1 else ''}")
        click.echo(f"Pinning: {', '.join(parts)}", err=True)
    sys.exit(0 if result.reward >= 0.98 else 1)
