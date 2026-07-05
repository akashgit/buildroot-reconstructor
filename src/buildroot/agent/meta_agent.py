"""Orchestrator agent — outer loop that spawns a Claude Code agent to drive reconstruction."""

from __future__ import annotations

import json
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from buildroot.agent.claude_runner import spawn_claude_agent
from buildroot.agent.evaluator import Evaluator
from buildroot.agent.knowledge.retrieval import DEFAULT_KB_DIR, query_kb_for_prompt
from buildroot.agent.meta_prompt import (
    build_orchestrator_prompt,
    build_trusted_orchestrator_prompt,
    _build_trusted_task_prompt,
)
from buildroot.agent.models import RecipeStore
from buildroot.agent.prepass import PrePassFindings, run_prepass
from buildroot.pipeline.models import BuildrootSpec, JdkSpec, PomData
from buildroot.pipeline.orchestrator import parse_gav
from buildroot.trust.delta import VariantResult, build_delta_report
from buildroot.trust.registry import TrustedSourceRegistry
from buildroot.trust.report import generate_trust_report
from buildroot.trust.sbom import generate_sbom

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    """Result from the orchestrator agent run."""

    coordinate: str = ""
    status: str = "budget_exhausted"
    best_reward: float = 0.0
    best_level: int = 0
    best_containerfile: str = ""
    best_containerfile_path: str = ""
    iterations: int = 0
    path: str = "v3"
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0
    error_message: str = ""
    comparison_report: dict | None = None
    build_log: str = ""
    trusted_reward: float = 0.0
    trusted_level: int = 0
    trusted_containerfile: str = ""
    trusted_containerfile_path: str = ""
    trusted_comparison_report: dict | None = None
    eval_result_dict: dict | None = None
    trusted_eval_result_dict: dict | None = None

    def to_dict(self) -> dict:
        d = {
            "coordinate": self.coordinate,
            "status": self.status,
            "best_reward": round(self.best_reward, 4),
            "best_level": self.best_level,
            "iterations": self.iterations,
            "path": self.path,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "cost_usd": round(self.cost_usd, 4),
        }
        if self.comparison_report is not None:
            d["comparison_report"] = self.comparison_report
        if self.build_log:
            d["build_log"] = self.build_log
        if self.trusted_reward > 0 or self.trusted_containerfile:
            trusted_d = {
                "reward": round(self.trusted_reward, 4),
                "level": self.trusted_level,
                "containerfile_path": self.trusted_containerfile_path,
            }
            if self.trusted_comparison_report is not None:
                trusted_d["comparison_report"] = self.trusted_comparison_report
            d["trusted"] = trusted_d
        return d

    def phase2_findings(self) -> dict:
        """Build a phase2 findings dict for handoff to phase 3."""
        findings: dict = {
            "best_containerfile": self.best_containerfile,
            "best_reward": self.best_reward,
            "best_level": self.best_level,
            "path": self.path,
        }
        if self.comparison_report is not None and self.best_level >= 3:
            findings["comparison_report"] = self.comparison_report
        if self.build_log:
            findings["build_log"] = self.build_log
        return findings


_BANNER = """\
\033[1;36m  ┏┓ ╻ ╻╻╻  ┏┓ ┏━┓┏━┓┏━┓╺┳╸\033[0m
\033[1;36m  ┣┻┓┃ ┃┃┃  ┃┃ ┣┳┛┃ ┃┃ ┃ ┃\033[0m
\033[1;36m  ┗━┛┗━┛╹┗━╸┗┛╸╹┗╸┗━┛┗━┛ ╹\033[0m
\033[2m  powered by re:factory\033[0m
"""


def launch_interactive_orchestrator(
    coordinate: str,
    *,
    host: str | None = None,
    workspace: Path | None = None,
    target_score: float = 0.98,
) -> int:
    """Run prepass + KB query, then launch an interactive Claude session with full context.

    Returns the claude process exit code.
    """
    import subprocess

    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="buildroot-interactive-"))
    workspace.mkdir(parents=True, exist_ok=True)

    group_id, artifact_id, version = parse_gav(coordinate)

    # 1. Pre-pass
    logger.info("Running pre-pass for %s", coordinate)
    prepass_findings = run_prepass(coordinate, workspace / "prepass")
    prepass_summary = prepass_findings.to_prompt()

    # 2. KB query
    build_system = None
    if prepass_findings.build_system:
        build_system = prepass_findings.build_system.value

    manifest_tags = []
    if prepass_findings.jar_manifest:
        if any(k.startswith("Bundle-") for k in prepass_findings.jar_manifest):
            manifest_tags.append("osgi")
        if prepass_findings.jar_manifest.get("Multi-Release") == "true":
            manifest_tags.append("multi-release")

    kb_context = query_kb_for_prompt(
        build_system=build_system,
        tags=manifest_tags or None,
        group_id=group_id,
        kb_dir=DEFAULT_KB_DIR,
    )

    # 3. Build system prompt
    system_prompt = build_orchestrator_prompt(
        coordinate=coordinate,
        prepass_summary=prepass_summary,
        kb_context=kb_context,
        v3_available=True,
    )

    # 4. Build task prompt
    task = _build_task_prompt(coordinate, host, workspace, target_score)

    # 5. Write prepass data to workspace
    prepass_json = workspace / "prepass_findings.json"
    prepass_json.write_text(json.dumps(prepass_findings.to_dict(), indent=2))

    # 6. Write system prompt + task to temp file
    prompt_file = Path(tempfile.mktemp(prefix="buildroot-prompt-", suffix=".md"))
    prompt_file.write_text(system_prompt + "\n\n---\n\n# Task\n\n" + task)

    # 7. Print banner then launch interactive claude as a subprocess.
    import sys
    print(_BANNER, file=sys.stderr)

    cmd = [
        "claude",
        f"Reconstruct {coordinate}",
        "--append-system-prompt-file", str(prompt_file),
        "--model", "claude-opus-4-6",
        "--dangerously-skip-permissions",
    ]

    try:
        result = subprocess.run(cmd)
        return result.returncode
    finally:
        prompt_file.unlink(missing_ok=True)


def _extract_jdk_version(prepass_findings: PrePassFindings) -> str:
    """Extract JDK version string from prepass manifest data."""
    manifest = prepass_findings.jar_manifest or {}
    jdk = manifest.get("Build-Jdk-Spec", "")
    if not jdk:
        created_by = manifest.get("Created-By", "")
        if created_by:
            for part in created_by.replace("(", " ").replace(")", " ").split():
                if part and part[0].isdigit():
                    jdk = part
                    break
    return jdk or "unknown"


def run_orchestrator(
    coordinate: str,
    *,
    host: str | None = None,
    workspace: Path | None = None,
    target_score: float = 0.98,
    max_budget_usd: float = 0,
    max_agent_turns: int = 0,
    agent_timeout: int = 0,
) -> OrchestratorResult:
    """Run the orchestrator: prepass → KB query → spawn Claude Code agent → parse result."""
    start_time = time.time()
    result = OrchestratorResult(coordinate=coordinate)

    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="buildroot-orch-"))
    workspace.mkdir(parents=True, exist_ok=True)

    group_id, artifact_id, version = parse_gav(coordinate)
    recipe_store = RecipeStore()

    existing_level = recipe_store.best_level(coordinate)
    if existing_level >= 4:
        existing_cf = recipe_store.get_containerfile(coordinate, 4)
        if existing_cf:
            logger.info("Recipe already exists at L4 for %s — skipping", coordinate)
            result.status = "recipe_skip"
            result.best_reward = 1.0
            result.best_level = 4
            result.best_containerfile = existing_cf
            result.elapsed_seconds = time.time() - start_time
            return result

    # 0. Sibling check — find a successful build of a different version
    sibling_context = ""
    try:
        from buildroot.agent.build_store import get_sibling_build

        sibling = get_sibling_build(group_id, artifact_id, exclude_version=version)
        if sibling:
            sibling_context = (
                f"\n## Sibling Build (same artifact, different version)\n\n"
                f"A successful L{sibling['level']} build exists for "
                f"`{sibling['group_id']}:{sibling['artifact_id']}:{sibling['version']}` "
                f"(reward={sibling['reward']}).\n\n"
                f"```dockerfile\n{sibling['containerfile']}\n```\n\n"
                f"**Adapt this for version {version}.** The build recipe is likely very similar — "
                f"update the git tag, version strings, and filenames. "
                f"Try evaluating the adapted version first before exploring other approaches.\n"
            )
            logger.info(
                "Found sibling build: %s:%s:%s (reward=%.4f)",
                sibling["group_id"], sibling["artifact_id"],
                sibling["version"], sibling["reward"],
            )
    except Exception as e:
        logger.debug("Sibling lookup skipped: %s", e)

    # 1. Pre-pass
    logger.info("Running pre-pass for %s", coordinate)
    try:
        prepass_findings = run_prepass(coordinate, workspace / "prepass")
    except Exception as e:
        logger.error("Pre-pass failed: %s", e)
        result.status = "prepass_failed"
        result.error_message = str(e)
        result.elapsed_seconds = time.time() - start_time
        return result

    prepass_summary = prepass_findings.to_prompt()

    # 2. KB query
    build_system = None
    if prepass_findings.build_system:
        build_system = prepass_findings.build_system.value

    manifest_tags = []
    if prepass_findings.jar_manifest:
        if any(k.startswith("Bundle-") for k in prepass_findings.jar_manifest):
            manifest_tags.append("osgi")
        if prepass_findings.jar_manifest.get("Multi-Release") == "true":
            manifest_tags.append("multi-release")

    kb_context = query_kb_for_prompt(
        build_system=build_system,
        tags=manifest_tags or None,
        group_id=group_id,
        kb_dir=DEFAULT_KB_DIR,
    )

    # 3. Build system prompt
    system_prompt = build_orchestrator_prompt(
        coordinate=coordinate,
        prepass_summary=prepass_summary,
        kb_context=kb_context,
        v3_available=True,
    )

    # 4. Build task prompt
    task = _build_task_prompt(coordinate, host, workspace, target_score)
    if sibling_context:
        task = task + "\n" + sibling_context

    # 5. Write prepass data to workspace for agent access
    prepass_json = workspace / "prepass_findings.json"
    prepass_json.write_text(json.dumps(prepass_findings.to_dict(), indent=2))

    # 6. Spawn the orchestrator agent
    logger.info("Spawning orchestrator agent for %s (budget=$%.2f, timeout=%s)",
                coordinate, max_budget_usd, f"{agent_timeout}s" if agent_timeout > 0 else "unlimited")

    agent_result = spawn_claude_agent(
        task=task,
        system_prompt=system_prompt,
        model="claude-opus-4-6",
        max_turns=max_agent_turns,
        max_budget_usd=max_budget_usd,
        timeout=agent_timeout,
        cwd=str(workspace),
        allowed_tools=["Bash", "Read", "Write", "Edit", "WebSearch", "WebFetch"],
    )

    result.cost_usd = agent_result.cost_usd
    result.elapsed_seconds = time.time() - start_time

    if agent_result.is_error:
        logger.error("Orchestrator agent failed: %s", agent_result.error_message)
        result.status = "agent_error"
        result.error_message = agent_result.error_message
    else:
        _parse_agent_output(agent_result.text, result, workspace, coordinate, host)

    # 7. Post-run: find best Containerfile in workspace
    _scan_workspace_for_best(result, workspace, coordinate, host)

    # 8. Learning loop — record success
    if result.best_reward >= target_score and result.best_containerfile:
        recipe_store.save(coordinate, 4, result.best_containerfile, result.best_reward)
        _record_learnings(
            coordinate=coordinate,
            containerfile=result.best_containerfile,
            reward=result.best_reward,
            prepass_findings=prepass_findings,
        )
        result.status = "success"

    # 9. Phase 3: Trusted cascade
    if result.best_containerfile:
        _run_trusted_phase(
            coordinate=coordinate,
            workspace=workspace,
            phase2_result=result,
            prepass_summary=prepass_summary,
            kb_context=kb_context,
            host=host,
            max_budget_usd=max_budget_usd,
            max_agent_turns=max_agent_turns,
            agent_timeout=agent_timeout,
            target_score=target_score,
        )

        # 10. Output restructuring
        _restructure_output(result, workspace, coordinate)

    # 11. Save to build store (L3+ builds for tracking and warm-start)
    if result.best_reward >= 0.5 and result.best_containerfile:
        try:
            from buildroot.agent.build_store import save_build

            delta = None
            delta_path = workspace / "delta_report.json"
            if delta_path.exists():
                delta = json.loads(delta_path.read_text())

            trust_md = ""
            trust_path = workspace / "trust_report.md"
            if trust_path.exists():
                trust_md = trust_path.read_text()

            prepass_data = None
            prepass_path = workspace / "prepass_findings.json"
            if prepass_path.exists():
                prepass_data = json.loads(prepass_path.read_text())

            save_build(
                coordinate, result.best_containerfile, result.best_reward,
                result.best_level, result.path, result.cost_usd, result.elapsed_seconds,
                trusted_containerfile=result.trusted_containerfile,
                trusted_reward=result.trusted_reward,
                trusted_level=result.trusted_level,
                delta_report=delta,
                trust_report=trust_md,
                prepass_findings=prepass_data,
                exact_comparison=result.comparison_report,
                trusted_comparison=result.trusted_comparison_report,
                eval_result=result.eval_result_dict,
                trusted_eval_result=result.trusted_eval_result_dict,
            )
        except Exception as e:
            logger.debug("Build store save skipped: %s", e)

    return result


def _run_trusted_phase(
    coordinate: str,
    workspace: Path,
    phase2_result: OrchestratorResult,
    prepass_summary: str,
    kb_context: str,
    host: str,
    max_budget_usd: float,
    max_agent_turns: int,
    agent_timeout: int,
    target_score: float,
) -> None:
    """Run Phase 3: same agent loop constrained to trusted sources, warm-started from Phase 2."""
    logger.info("Starting Phase 3 (trusted cascade) for %s", coordinate)

    trusted_workspace = workspace / "trusted"
    trusted_workspace.mkdir(parents=True, exist_ok=True)

    phase2_findings = phase2_result.phase2_findings()

    if phase2_result.best_containerfile:
        ref_path = trusted_workspace / "phase2_reference.Containerfile"
        ref_path.write_text(phase2_result.best_containerfile)

    system_prompt = build_trusted_orchestrator_prompt(
        coordinate=coordinate,
        prepass_summary=prepass_summary,
        kb_context=kb_context,
        phase2_findings=phase2_findings,
    )

    task = _build_trusted_task_prompt(
        coordinate=coordinate,
        host=host,
        workspace=trusted_workspace,
        target_score=target_score,
    )

    remaining_budget = 0.0
    if max_budget_usd > 0:
        remaining_budget = max(0.0, max_budget_usd - phase2_result.cost_usd)
        if remaining_budget <= 0:
            logger.warning("No budget remaining for Phase 3")
            return

    logger.info(
        "Spawning Phase 3 trusted agent (budget=$%.2f, timeout=%s)",
        remaining_budget, f"{agent_timeout}s" if agent_timeout > 0 else "unlimited",
    )

    agent_result = spawn_claude_agent(
        task=task,
        system_prompt=system_prompt,
        model="claude-opus-4-6",
        max_turns=max_agent_turns,
        max_budget_usd=remaining_budget,
        timeout=agent_timeout,
        cwd=str(trusted_workspace),
        allowed_tools=["Bash", "Read", "Write", "Edit", "WebSearch", "WebFetch"],
    )

    phase2_result.cost_usd += agent_result.cost_usd

    if not agent_result.is_error:
        trusted_result = OrchestratorResult(coordinate=coordinate)
        _parse_agent_output(agent_result.text, trusted_result, trusted_workspace, coordinate, host)
        _scan_workspace_for_best(trusted_result, trusted_workspace, coordinate, host)

        phase2_result.trusted_reward = trusted_result.best_reward
        phase2_result.trusted_level = trusted_result.best_level
        phase2_result.trusted_containerfile = trusted_result.best_containerfile
        phase2_result.trusted_containerfile_path = trusted_result.best_containerfile_path
        phase2_result.trusted_comparison_report = trusted_result.comparison_report
        phase2_result.trusted_eval_result_dict = trusted_result.eval_result_dict
        logger.info(
            "Phase 3 complete: trusted_reward=%.4f, trusted_level=%d",
            trusted_result.best_reward, trusted_result.best_level,
        )
    else:
        logger.error("Phase 3 agent failed: %s", agent_result.error_message)


def _build_task_prompt(
    coordinate: str,
    host: str | None,
    workspace: Path,
    target_score: float,
) -> str:
    """Build the task prompt given to the orchestrator agent."""
    host_flag = f" --host {host}" if host else ""
    build_mode = f"Build host: {host} (use SSH for all podman commands)" if host else "Builds run locally via podman."
    return f"""\
Reconstruct the Maven Central artifact: {coordinate}

{build_mode}
Workspace: {workspace}
Target score: {target_score}

## Instructions

1. **Try v3 first** (fast path):
   ```bash
   buildroot agent {coordinate} --v3-only --max-iterations 1{host_flag}
   ```
   Read the JSON output. If reward >= {target_score}, you're done.

2. **If v3 stagnates or can't solve it**, take over:
   - Read the v3 workspace for the best Containerfile so far
   - Write your own Containerfile at {workspace}/Containerfile
   - Evaluate it:
     ```bash
     buildroot eval {workspace}/Containerfile {coordinate}{host_flag}
     ```
   - Read the comparison report, fix what's failing, iterate

3. **Save your best Containerfile** to {workspace}/Containerfile.best

4. **Output your final result** in this exact format on the last line:
   ```
   RESULT: SUCCESS|STAGNATION|BUDGET_EXHAUSTED coordinate={coordinate} reward=<float> level=<int> path=<v3|takeover>
   ```
"""


def _parse_agent_output(
    text: str,
    result: OrchestratorResult,
    workspace: Path,
    coordinate: str,
    host: str | None = None,
) -> None:
    """Parse the orchestrator agent's text output for structured result info."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("RESULT:"):
            parts = line.split()
            for part in parts:
                if part.startswith("reward="):
                    try:
                        result.best_reward = float(part.split("=", 1)[1])
                    except ValueError:
                        pass
                elif part.startswith("level="):
                    try:
                        result.best_level = int(part.split("=", 1)[1])
                    except ValueError:
                        pass
                elif part.startswith("path="):
                    result.path = part.split("=", 1)[1]

            if "SUCCESS" in line:
                result.status = "success"
            elif "STAGNATION" in line:
                result.status = "stagnation"
            elif "BUDGET_EXHAUSTED" in line:
                result.status = "budget_exhausted"
            break


def _scan_workspace_for_best(
    result: OrchestratorResult,
    workspace: Path,
    coordinate: str,
    host: str | None = None,
) -> None:
    """Scan workspace for Containerfile.best or Containerfile and evaluate if needed."""
    best_cf_path = workspace / "Containerfile.best"
    fallback_cf_path = workspace / "Containerfile"

    cf_path = None
    if best_cf_path.exists():
        cf_path = best_cf_path
    elif fallback_cf_path.exists():
        cf_path = fallback_cf_path

    if cf_path is None:
        return

    cf_text = cf_path.read_text().strip()
    if not cf_text:
        return

    result.best_containerfile = cf_text
    result.best_containerfile_path = str(cf_path)

    try:
        jdk_version = ""
        prepass_json = workspace / "prepass_findings.json"
        if prepass_json.exists():
            try:
                pdata = json.loads(prepass_json.read_text())
                manifest = pdata.get("jar_manifest") or {}
                jdk_version = manifest.get("Build-Jdk-Spec", "")
                if not jdk_version:
                    created_by = manifest.get("Created-By", "")
                    for part in created_by.replace("(", " ").replace(")", " ").split():
                        if part and part[0].isdigit():
                            jdk_version = part
                            break
            except (json.JSONDecodeError, OSError):
                pass

        evaluator = Evaluator(host=host)
        eval_result = evaluator.evaluate(cf_text, coordinate, jdk_version=jdk_version)
        result.best_reward = eval_result.reward
        result.best_level = eval_result.level_reached
        result.eval_result_dict = eval_result.to_dict()
        if eval_result.comparison_report is not None:
            report = eval_result.comparison_report
            result.comparison_report = {
                "structural_match": report.structural.match,
                "metadata_match": report.metadata.match,
                "bytecode_match": report.bytecode.match,
                "verdict": report.verdict,
            }
        result.build_log = eval_result.build_log
    except Exception as e:
        logger.warning("Post-scan evaluation failed: %s", e)
        result.best_reward = 0.0
        result.best_level = 0


def _record_learnings(
    *,
    coordinate: str,
    containerfile: str,
    reward: float,
    prepass_findings: PrePassFindings,
) -> None:
    """Record successful approach to the knowledge base (learning loop)."""
    from buildroot.agent.knowledge.schema import TemplateEntry, save_entry

    group_id, artifact_id, version = parse_gav(coordinate)

    build_system = "maven"
    if prepass_findings.build_system:
        build_system = prepass_findings.build_system.value

    tags = [build_system]
    if prepass_findings.jar_manifest:
        if any(k.startswith("Bundle-") for k in prepass_findings.jar_manifest):
            tags.append("osgi")
        if prepass_findings.jar_manifest.get("Multi-Release") == "true":
            tags.append("multi-release")

    safe_name = f"template-{artifact_id}-{version}".replace(".", "-")
    template = TemplateEntry(
        name=safe_name,
        description=f"Winning Containerfile for {coordinate} (L4={reward:.4f})",
        tags=tags,
        build_systems=[build_system],
        containerfile=containerfile,
        coordinate=coordinate,
        l4_score=reward,
        times_used=1,
        success_rate=1.0,
    )

    try:
        save_entry(template, DEFAULT_KB_DIR)
        logger.info("Recorded winning template for %s", coordinate)
    except Exception as e:
        logger.warning("Failed to record learning for %s: %s", coordinate, e)

    _update_matched_kb_entries(
        build_system=build_system,
        tags=tags,
        group_id=group_id,
    )


def _update_matched_kb_entries(
    *,
    build_system: str,
    tags: list[str],
    group_id: str,
) -> None:
    """Update times_used and success_rate on matched KB entries."""
    from buildroot.agent.knowledge.schema import load_all_entries, save_entry

    entries = load_all_entries(DEFAULT_KB_DIR)
    for entry in entries:
        matched = False
        if build_system and build_system in [bs.lower() for bs in entry.build_systems]:
            matched = True
        if tags:
            entry_tags_lower = {t.lower() for t in entry.tags}
            if any(t.lower() in entry_tags_lower for t in tags):
                matched = True

        if matched:
            entry.times_used += 1
            total = entry.times_used
            entry.success_rate = ((entry.success_rate * (total - 1)) + 1.0) / total
            try:
                save_entry(entry, DEFAULT_KB_DIR)
            except Exception:
                pass


def _build_variant_result_from_cascade(
    containerfile_path: str,
    result: OrchestratorResult,
    variant_type: str,
) -> VariantResult:
    """Build a VariantResult from cascade pipeline output."""
    base_image = ""
    jdk_version = ""
    if result.best_containerfile:
        for line in result.best_containerfile.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("FROM "):
                base_image = stripped.split()[1]
                break

    registry = TrustedSourceRegistry()
    trusted, source = registry.is_trusted_image(base_image)
    jdk_source = source.provider if source else "unknown"
    provenance_tier = source.tier.value if source else None

    return VariantResult(
        name=variant_type,
        containerfile_path=Path(containerfile_path) if containerfile_path else Path(),
        base_image=base_image,
        jdk_version=jdk_version,
        jdk_source=jdk_source,
        provenance_tier=provenance_tier,
    )


def _load_or_build_spec(variant_dir: str) -> BuildrootSpec:
    """Load BuildrootSpec from buildroot.json or construct a minimal one."""
    br_path = Path(variant_dir) / "buildroot.json"
    if br_path.exists():
        try:
            data = json.loads(br_path.read_text())
            pom = PomData(
                group_id=data.get("group_id", ""),
                artifact_id=data.get("artifact_id", ""),
                version=data.get("version", ""),
            )
            jdk_data = data.get("jdk_version", {})
            jdk = JdkSpec(
                version=jdk_data.get("value", "") if isinstance(jdk_data, dict) else str(jdk_data),
                base_image=data.get("base_image", ""),
            )
            return BuildrootSpec(pom_data=pom, jdk_spec=jdk)
        except (json.JSONDecodeError, OSError):
            pass
    return BuildrootSpec()


def _restructure_output(
    result: OrchestratorResult,
    workspace: Path,
    coordinate: str,
    output_dir: Path | None = None,
) -> None:
    """Generate trust artifacts (delta_report, trust_report, SBOM) and copy to output_dir."""
    group_id, artifact_id, version = parse_gav(coordinate)

    exact_dir = workspace / "exact"
    trusted_dir = workspace / "trusted"
    exact_dir.mkdir(parents=True, exist_ok=True)
    trusted_dir.mkdir(parents=True, exist_ok=True)

    if result.best_containerfile:
        (exact_dir / "Containerfile").write_text(result.best_containerfile)

    exact_result = _build_variant_result_from_cascade(
        str(exact_dir / "Containerfile"), result, "exact",
    )
    trusted_result = _build_variant_result_from_cascade(
        str(trusted_dir / "Containerfile") if (trusted_dir / "Containerfile").exists() else "",
        result,
        "trusted",
    )

    delta = build_delta_report(exact_result, trusted_result)
    delta.coordinate = coordinate
    delta.exact_reward = result.best_reward
    delta.trusted_reward = result.trusted_reward
    delta.reward_delta = result.trusted_reward - result.best_reward

    if isinstance(result.comparison_report, dict):
        cr = result.comparison_report
        delta.structural_match = cr.get("structural_match")
        delta.metadata_match = cr.get("metadata_match")
        delta.bytecode_match = cr.get("bytecode_match")
        verdict = cr.get("verdict", "")
        if verdict in ("IDENTICAL", "EQUIVALENT", "DIVERGENT"):
            delta.functional_equivalence = verdict

    if isinstance(result.trusted_comparison_report, dict):
        tcr = result.trusted_comparison_report
        trusted_verdict = tcr.get("verdict", "")
        if delta.functional_equivalence in ("", "NOT_EVALUATED") and trusted_verdict in ("IDENTICAL", "EQUIVALENT", "DIVERGENT"):
            delta.functional_equivalence = trusted_verdict
            delta.structural_match = tcr.get("structural_match")
            delta.metadata_match = tcr.get("metadata_match")
            delta.bytecode_match = tcr.get("bytecode_match")

    delta_path = workspace / "delta_report.json"
    delta_path.write_text(json.dumps(delta.to_dict(), indent=2) + "\n")

    spec = _load_or_build_spec(str(workspace))
    spec.pom_data.group_id = group_id
    spec.pom_data.artifact_id = artifact_id
    spec.pom_data.version = version

    generate_trust_report(spec, delta, workspace)
    generate_sbom(spec, "exact", exact_dir)
    generate_sbom(spec, "trusted", trusted_dir)

    if output_dir is not None:
        import shutil

        gav_dir = output_dir / group_id.replace(".", "/") / artifact_id / version
        gav_dir.mkdir(parents=True, exist_ok=True)
        for item_name in ["exact", "trusted", "delta_report.json", "trust_report.md"]:
            src = workspace / item_name
            dst = gav_dir / item_name
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            elif src.is_file():
                shutil.copy2(src, dst)
