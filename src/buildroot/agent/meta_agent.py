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
from buildroot.agent.meta_prompt import build_orchestrator_prompt
from buildroot.agent.models import RecipeStore
from buildroot.agent.prepass import PrePassFindings, run_prepass
from buildroot.pipeline.orchestrator import parse_gav

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

    def to_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "status": self.status,
            "best_reward": round(self.best_reward, 4),
            "best_level": self.best_level,
            "iterations": self.iterations,
            "path": self.path,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "cost_usd": round(self.cost_usd, 4),
        }


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

    return result


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
   buildroot agent {coordinate} --v3-only --max-iterations 5{host_flag}
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

    if result.best_reward < 0.01:
        try:
            evaluator = Evaluator(host=host)
            eval_result = evaluator.evaluate(cf_text, coordinate)
            result.best_reward = eval_result.reward
            result.best_level = eval_result.level_reached
        except Exception as e:
            logger.warning("Post-scan evaluation failed: %s", e)


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
