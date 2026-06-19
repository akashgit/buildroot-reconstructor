"""Pipeline v3 — single Analysis Agent with full tools, structured feedback, and loop control."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from buildroot.agent.claude_runner import spawn_claude_agent
from buildroot.agent.evaluator import Evaluator
from buildroot.agent.models import EvalResult, FailedApproach, RecipeStore
from buildroot.agent.scorer import ScoreBreakdown, build_score_breakdown, compute_fallback_score
from buildroot.agent.prepass import PrePassFindings, run_prepass
from buildroot.generators.containerfile import ContainerfileGenerator
from buildroot.pipeline.models import BuildrootSpec
from buildroot.pipeline.orchestrator import parse_gav

logger = logging.getLogger(__name__)


BUILDROOT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_repo": {
            "type": "string",
            "description": "Git clone URL for the source repository",
        },
        "git_tag": {
            "type": "string",
            "description": "Git tag or branch to checkout",
        },
        "jdk_version": {
            "type": "string",
            "description": "JDK major version (e.g. '17', '11', '8')",
        },
        "jdk_minor_version": {
            "type": ["string", "null"],
            "description": "Exact JDK minor version (e.g. '17.0.9') — controls Docker image tag",
        },
        "jdk_distribution": {
            "type": "string",
            "description": "JDK distribution (e.g. 'temurin', 'openjdk', 'corretto')",
        },
        "build_command": {
            "type": "string",
            "description": "Main build command (e.g. 'mvn clean install -B -DskipTests')",
        },
        "build_system": {
            "type": "string",
            "enum": ["maven", "gradle", "ant", "custom"],
            "description": "Build system — selects template",
        },
        "maven_version": {
            "type": ["string", "null"],
            "description": "Maven version string (e.g. '3.9.6')",
        },
        "build_tool_version": {
            "type": ["string", "null"],
            "description": "Build tool version (Gradle version, Ant version)",
        },
        "base_image": {
            "type": ["string", "null"],
            "description": "Custom Docker base image override",
        },
        "system_packages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "apt packages to install",
        },
        "pre_build_commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Shell commands to run before the build",
        },
        "post_build_commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Shell commands to run after the build",
        },
        "config_files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
            "description": "Files to create before build (e.g. settings.xml)",
        },
        "env_vars": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Environment variables to set",
        },
        "template_id": {
            "type": ["string", "null"],
            "description": "Explicit template override (e.g. 'gradle_base.j2')",
        },
        "module_path": {
            "type": ["string", "null"],
            "description": "Maven module path for -pl flag in multi-module projects",
        },
        "artifact_path_pattern": {
            "type": ["string", "null"],
            "description": "Glob pattern for finding the built JAR",
        },
        "use_maven_wrapper": {
            "type": "boolean",
            "description": "If true, template uses ./mvnw instead of mvn",
        },
        "confidence_notes": {
            "type": ["string", "null"],
            "description": "Free-text notes about your reasoning",
        },
    },
    "required": [
        "source_repo", "git_tag", "jdk_version", "jdk_distribution",
        "build_command", "build_system",
    ],
}

ANALYSIS_AGENT_SYSTEM = """\
You are the Analysis Agent for the buildroot reconstruction pipeline. Your goal is to \
determine the exact build environment needed to reproduce a Maven Central artifact \
as a Containerfile.

## Investigation Strategy (6 steps)

1. **Review Pre-Pass findings** — the deterministic pre-pass has already gathered POM data, \
manifest info, JDK version, source repo, git tag, and CI workflow data. Start from these.
2. **Clone and inspect the source repo** — use `git clone --depth 1 <repo> -b <tag>` to get \
the source. Read pom.xml, build.gradle, .mvn/wrapper, and CI configs directly.
3. **Cross-reference JDK version** — the manifest Build-Jdk-Spec tells you what JDK was used. \
Match this to a Docker image tag (e.g. eclipse-temurin:17.0.9-jdk).
4. **Analyze build plugins** — identify plugins that affect reproducibility (maven-shade-plugin, \
maven-assembly-plugin, maven-jar-plugin configuration).
5. **Check for reproducibility requirements** — SOURCE_DATE_EPOCH=0, \
project.build.outputTimestamp, GPG signing skip, metadata stripping.
6. **Validate the build command** — ensure all flags are correct for the build system. \
Skip tests unless they're needed for the artifact.

## Evidence Hierarchy (highest to lowest)

1. **direct_observation** — you cloned the repo and read the file yourself
2. **ci_inference** — extracted from CI workflow YAML
3. **cross_reference** — corroborated across multiple sources
4. **ecosystem_heuristic** — common pattern for this project type
5. **default** — reasonable default when no signal exists

## Critical Rules

- **Apache reproducibility**: For Apache projects, add `-Papache-release` if the profile exists, \
and always use `-Dproject.build.outputTimestamp=2000-01-01T00:00:00Z`.
- **GPG signing**: Always add `-Dgpg.skip=true` — we don't have signing keys.
- **SOURCE_DATE_EPOCH**: Always set `SOURCE_DATE_EPOCH=0` in env_vars for reproducible timestamps.
- **Gradle projects**: Set build_system to "gradle" and use `./gradlew build -x test` as \
the build command. The template handles the rest.
- **Ant projects**: Set build_system to "ant" and use `ant jar` or `ant dist` as the build command.
- **Maven wrapper**: If the repo has .mvn/wrapper/, set use_maven_wrapper to true. \
The template automatically switches mvn → ./mvnw and adds chmod +x.
- **Multi-module projects**: Set module_path to the module containing the target artifact. \
Add `-pl <module> -am` to the build command.
- **JDK minor version**: When the manifest shows a specific minor version (e.g. 17.0.9), \
set jdk_minor_version to match — different minor versions produce different bytecode.

## Output Format

Output COMPLETE template values as a JSON object matching the schema. \
Include ALL fields — do not output incremental changes. \
Every iteration must be a complete specification.
"""

MULTI_VARIANT_SCHEMA = {
    "type": "object",
    "properties": {
        "variants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Why this variant might work",
                    },
                    "template_values": BUILDROOT_SCHEMA,
                },
                "required": ["reasoning", "template_values"],
            },
            "minItems": 1,
            "maxItems": 3,
            "description": "1-3 ranked variants to try (best first)",
        },
    },
    "required": ["variants"],
}

FEEDBACK_AGENT_SYSTEM = """\
You are the Analysis Agent continuing to refine a build environment. You have already \
produced an initial set of template values that were built and evaluated. Review the \
feedback below and output UPDATED COMPLETE template values.

## Rules

- Output the FULL set of template values every time — not incremental changes.
- Do NOT retry approaches listed in "Failed Approaches".
- Read the build log and comparison report files for detailed investigation.
- At L4, use diff -r and javap -v on the unpacked JARs to diagnose divergences.
- Focus on the specific failing dimension (structural, metadata, or bytecode).
- You may output 1-3 RANKED variants in the "variants" array.
  Each variant must contain a "reasoning" field and a complete "template_values" object.
  The system will automatically prepend the current best as an incumbent — \
  you only need to output NEW variants to try.

## Evidence Hierarchy

1. direct_observation > 2. ci_inference > 3. cross_reference > 4. ecosystem_heuristic > 5. default

## Critical Rules

- Always set SOURCE_DATE_EPOCH=0 in env_vars
- Always add -Dgpg.skip=true for Maven builds
- Use -Dproject.build.outputTimestamp=2000-01-01T00:00:00Z for Maven
- Match JDK minor version exactly when bytecode diverges
"""


@dataclass
class PipelineResult:
    """Result from the v3 pipeline."""

    coordinate: str = ""
    status: str = "budget_exhausted"
    best_reward: float = 0.0
    best_values: dict = field(default_factory=dict)
    best_containerfile: str = ""
    iterations: int = 0
    elapsed_seconds: float = 0.0
    score_history: list[dict] = field(default_factory=list)
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "status": self.status,
            "best_reward": self.best_reward,
            "iterations": self.iterations,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "score_history": self.score_history,
        }


def _spec_to_dict(spec: BuildrootSpec) -> dict:
    """Convert BuildrootSpec to template values dict."""
    return {
        "source_repo": spec.source_repo,
        "git_tag": spec.git_tag,
        "jdk_version": spec.jdk_spec.version,
        "jdk_minor_version": spec.jdk_minor_version,
        "jdk_distribution": spec.jdk_spec.distribution,
        "build_command": spec.build_commands[0] if spec.build_commands else "",
        "build_system": spec.build_system or "maven",
        "maven_version": spec.maven_version or None,
        "build_tool_version": spec.build_tool_version,
        "base_image": spec.base_image or None,
        "system_packages": spec.system_packages,
        "pre_build_commands": spec.pre_build_commands,
        "post_build_commands": spec.post_build_commands,
        "config_files": spec.config_files,
        "env_vars": spec.reproducibility_env,
        "template_id": spec.template_id or None,
        "module_path": spec.module_path,
        "artifact_path_pattern": spec.artifact_path_pattern,
        "use_maven_wrapper": spec.use_maven_wrapper,
        "confidence_notes": None,
    }


def _dict_to_spec(values: dict) -> BuildrootSpec:
    """Convert template values dict to BuildrootSpec."""
    from buildroot.pipeline.models import JdkSpec

    build_cmd = values.get("build_command", "")
    build_commands = [build_cmd] if build_cmd else []

    env_vars = values.get("env_vars") or {}

    spec = BuildrootSpec(
        source_repo=values.get("source_repo", ""),
        git_tag=values.get("git_tag", ""),
        jdk_spec=JdkSpec(
            version=values.get("jdk_version", ""),
            distribution=values.get("jdk_distribution", "temurin"),
        ),
        jdk_minor_version=values.get("jdk_minor_version"),
        build_commands=build_commands,
        build_system=values.get("build_system", "maven"),
        maven_version=values.get("maven_version", ""),
        build_tool_version=values.get("build_tool_version"),
        base_image=values.get("base_image", ""),
        system_packages=values.get("system_packages") or [],
        pre_build_commands=values.get("pre_build_commands") or [],
        post_build_commands=values.get("post_build_commands") or [],
        config_files=values.get("config_files") or [],
        reproducibility_env=env_vars,
        template_id=values.get("template_id", ""),
        module_path=values.get("module_path"),
        artifact_path_pattern=values.get("artifact_path_pattern"),
        use_maven_wrapper=values.get("use_maven_wrapper", False),
    )

    if spec.jdk_spec.version and not spec.jdk_spec.base_image:
        minor = spec.jdk_minor_version
        if minor:
            spec.jdk_spec.base_image = f"eclipse-temurin:{minor}-jdk"
        else:
            spec.jdk_spec.base_image = f"eclipse-temurin:{spec.jdk_spec.version}-jdk"

    return spec


def _render_containerfile(values: dict) -> str:
    """Render template values to a Containerfile string."""
    import tempfile

    spec = _dict_to_spec(values)
    generator = ContainerfileGenerator()
    with tempfile.TemporaryDirectory(prefix="buildroot-v3-") as tmpdir:
        cf_path, _ = generator.generate(spec, Path(tmpdir))
        return cf_path.read_text()


def run_v3_pipeline(
    coordinate: str,
    *,
    max_iterations: int = 10,
    host: str = "rh-h100-01",
    workspace: Path | None = None,
    skip_deps: bool = True,
    warm_start_containerfile: str | None = None,
) -> PipelineResult:
    """Run the v3 pipeline: pre-pass → analysis agent → build+eval → feedback loop."""
    import tempfile

    start_time = time.time()
    result = PipelineResult(coordinate=coordinate)

    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="buildroot-v3-ws-"))
    workspace.mkdir(parents=True, exist_ok=True)

    group_id, artifact_id, version = parse_gav(coordinate)
    evaluator = Evaluator(host=host)
    recipe_store = RecipeStore()

    # Recipe store check
    existing_level = recipe_store.best_level(coordinate)
    if existing_level >= 4:
        existing_cf = recipe_store.get_containerfile(coordinate, 4)
        if existing_cf:
            result.status = "recipe_skip"
            result.best_reward = 1.0
            result.elapsed_seconds = time.time() - start_time
            return result

    # 1. Deterministic pre-pass
    logger.info("Running pre-pass for %s", coordinate)
    try:
        prepass_findings = run_prepass(coordinate, workspace / "prepass")
    except Exception as e:
        logger.error("Pre-pass failed: %s", e)
        result.status = "prepass_failed"
        result.error_message = str(e)
        result.elapsed_seconds = time.time() - start_time
        return result

    # Warm-start: reverse-parse existing Containerfile and start in feedback mode
    if warm_start_containerfile:
        logger.info("Warm-start: reverse-parsing existing Containerfile for %s", coordinate)
        current_values = reverse_parse_containerfile(warm_start_containerfile)
        current_values = _ensure_defaults(current_values, prepass_findings)
    else:
        # 2. Cross-package hints
        group_hints = recipe_store.get_group_hints(coordinate)

        # 3. Parallel first build: run fallback build AND analysis agent concurrently
        logger.info("Running initial analysis agent for %s", coordinate)
        initial_task = _build_initial_task(coordinate, prepass_findings, group_hints)

        fallback_values = _fallback_values_from_prepass(prepass_findings, coordinate)
        fallback_values = _ensure_defaults(fallback_values, prepass_findings)

        draft_result: EvalResult | None = None
        try:
            draft_cf = _render_containerfile(fallback_values)
            logger.info("Parallel first build: evaluating pre-pass draft while agent analyzes")
            draft_result = evaluator.evaluate(draft_cf, coordinate)
            logger.info("  Draft build: reward=%.4f level=%d", draft_result.reward, draft_result.level_reached)
        except Exception as e:
            logger.warning("Draft build failed (non-fatal): %s", e)

        agent_result = spawn_claude_agent(
            task=initial_task,
            system_prompt=ANALYSIS_AGENT_SYSTEM,
            model="claude-opus-4-6",
            json_schema=BUILDROOT_SCHEMA,
            max_turns=30,
            max_budget_usd=10.0,
            timeout=900,
            allowed_tools=["Bash", "Read", "WebSearch", "WebFetch", "Agent"],
        )

        if draft_result and draft_result.reward >= 0.98:
            logger.info("Draft build already near-perfect (%.4f) — using draft values", draft_result.reward)
            current_values = fallback_values
        elif agent_result.is_error or not agent_result.structured_output:
            logger.warning("Initial analysis agent failed: %s", agent_result.error_message)
            current_values = fallback_values
        else:
            current_values = agent_result.structured_output

        # Fill in defaults
        current_values = _ensure_defaults(current_values, prepass_findings)

    best_values = dict(current_values)
    best_reward = 0.0
    best_containerfile = ""
    failed_approaches: list[FailedApproach] = []
    value_hashes: list[str] = []
    prev_values: dict | None = None
    prev_reward: float = 0.0
    stagnation_count = 0
    fallback_stagnation = 0
    no_jar_count = 0

    for t in range(max_iterations):
        logger.info("Iteration %d/%d for %s", t + 1, max_iterations, coordinate)

        # Render Containerfile
        try:
            containerfile = _render_containerfile(current_values)
        except Exception as e:
            logger.error("Template render failed: %s", e)
            result.score_history.append({
                "iteration": t + 1, "reward": 0.0, "level": 0,
                "delta": 0.0, "error": str(e),
            })
            current_values = best_values
            continue

        # Build + Evaluate
        eval_result = evaluator.evaluate(containerfile, coordinate)
        reward = eval_result.reward
        level = eval_result.level_reached

        delta = reward - best_reward
        result.score_history.append({
            "iteration": t + 1,
            "reward": round(reward, 4),
            "level": level,
            "delta": round(delta, 4),
        })
        result.iterations = t + 1

        logger.info("  reward=%.4f level=%d delta=%+.4f", reward, level, delta)

        # Write build artifacts to workspace
        build_log_path = workspace / f"build_iter{t+1}.log"
        build_log_path.write_text(eval_result.build_log or "")
        cf_path = workspace / f"containerfile_iter{t+1}.txt"
        cf_path.write_text(containerfile)

        # Build score breakdown for fallback scoring
        score_bd = build_score_breakdown(eval_result, coordinate)

        # l3_ceiling termination: no JAR produced, no fallback signals
        if level <= 2 and not eval_result.l3_command:
            no_jar_count += 1
        else:
            no_jar_count = 0

        if no_jar_count >= 3 and not score_bd.jar_available:
            logger.info("  l3_ceiling: no JAR produced for %d iterations — terminating", no_jar_count)
            result.status = "l3_ceiling"
            break

        # fallback_ceiling_reached: using fallback signals + reward >= 0.85 + stagnation
        if score_bd.signal_source == "fallback_signals" and reward >= 0.85:
            fallback_stagnation += 1
            if fallback_stagnation >= 2:
                logger.info("  fallback_ceiling: reward=%.4f with fallback signals, stag=%d — terminating",
                           reward, fallback_stagnation)
                result.status = "fallback_ceiling_reached"
                break
        else:
            fallback_stagnation = 0

        # Save recipe at each level
        if level > 0:
            recipe_store.save(coordinate, level, containerfile, reward)

        # Track dead-end approaches
        if prev_values is not None:
            _record_failed_approaches(
                failed_approaches, prev_values, current_values,
                prev_reward, reward, t,
            )

        # Elitist gate
        if reward > best_reward:
            best_reward = reward
            best_values = dict(current_values)
            best_containerfile = containerfile
            stagnation_count = 0
        elif reward < best_reward:
            logger.info("  Regression: %.4f < best %.4f — reverting to best values", reward, best_reward)
            current_values = dict(best_values)

        # Stagnation detection
        current_hash = _hash_template_values(current_values)
        if current_hash == (value_hashes[-1] if value_hashes else "") and reward == prev_reward:
            stagnation_count += 1
        else:
            if reward >= best_reward:
                stagnation_count = 0
        value_hashes.append(current_hash)

        # Oscillation detection (A-B-A pattern)
        if len(value_hashes) >= 3:
            if value_hashes[-1] == value_hashes[-3] and value_hashes[-1] != value_hashes[-2]:
                logger.info("  Oscillation detected — terminating")
                result.status = "oscillation"
                break

        # Stagnation termination
        if stagnation_count >= 2:
            logger.info("  Stagnation detected (%d consecutive) — terminating", stagnation_count)
            result.status = "stagnation"
            break

        # Success check — double confirmation
        if reward >= 0.98:
            logger.info("  Reward >= 0.98 — running double confirmation...")
            confirm1 = evaluator.evaluate(containerfile, coordinate)
            confirm2 = evaluator.evaluate(containerfile, coordinate)
            if confirm1.reward >= 0.98 and confirm2.reward >= 0.98:
                result.status = "success"
                recipe_store.save(coordinate, 4, containerfile, reward)
                break
            else:
                logger.info("  Confirmation failed (%.4f, %.4f)", confirm1.reward, confirm2.reward)

        if t >= max_iterations - 1:
            break

        # Build feedback and call agent for next iteration
        prev_values = dict(current_values)
        prev_reward = reward

        from buildroot.agent.feedback import build_feedback_context
        feedback = build_feedback_context(
            current_values=current_values,
            best_values=best_values,
            eval_result=eval_result,
            comparison_report=None,
            score_history=result.score_history,
            failed_approaches=failed_approaches,
            containerfile=containerfile,
            workspace=workspace,
            iteration=t + 1,
        )

        feedback_task = (
            f"Refine the build environment for {coordinate}.\n\n"
            f"{feedback}\n\n"
            f"Output 1-3 ranked variants in the 'variants' array. "
            f"Each variant must have 'reasoning' and 'template_values' fields."
        )

        feedback_result = spawn_claude_agent(
            task=feedback_task,
            system_prompt=FEEDBACK_AGENT_SYSTEM,
            model="claude-opus-4-6",
            json_schema=MULTI_VARIANT_SCHEMA,
            max_turns=15,
            max_budget_usd=5.0,
            timeout=600,
            allowed_tools=["Bash", "Read", "WebSearch", "WebFetch", "Agent"],
        )

        if feedback_result.is_error or not feedback_result.structured_output:
            logger.warning("Feedback agent failed — retrying with best values")
            current_values = dict(best_values)
        else:
            # Multi-variant elitist: prepend incumbent, eval all, pick winner
            agent_variants = feedback_result.structured_output.get("variants", [])
            all_variants = [
                {"template_values": dict(best_values), "reasoning": "incumbent best", "is_incumbent": True},
            ]
            for v in agent_variants[:3]:
                tv = v.get("template_values", {})
                tv = _ensure_defaults(tv, prepass_findings)
                all_variants.append({
                    "template_values": tv,
                    "reasoning": v.get("reasoning", ""),
                    "is_incumbent": False,
                })

            if len(all_variants) <= 2:
                # Single new variant — just use it directly (no parallel overhead)
                current_values = all_variants[-1]["template_values"]
            else:
                # Multiple variants — build and evaluate all, pick winner
                variant_results = []
                for vi, v in enumerate(all_variants):
                    try:
                        v_cf = _render_containerfile(v["template_values"])
                        v_eval = evaluator.evaluate(v_cf, coordinate)
                        variant_results.append((vi, v_eval.reward, v_eval, v_cf))
                        logger.info("  Variant %d (%s): reward=%.4f",
                                   vi, "incumbent" if v.get("is_incumbent") else "new", v_eval.reward)
                    except Exception as e:
                        logger.warning("  Variant %d failed: %s", vi, e)
                        variant_results.append((vi, 0.0, None, ""))

                if variant_results:
                    winner_idx, winner_reward, winner_eval, winner_cf = max(
                        variant_results, key=lambda x: x[1],
                    )
                    current_values = all_variants[winner_idx]["template_values"]
                    if winner_eval and winner_reward > reward:
                        eval_result = winner_eval
                        containerfile = winner_cf
                        reward = winner_reward
                        logger.info("  Winner: variant %d (reward=%.4f)", winner_idx, winner_reward)
                else:
                    current_values = dict(best_values)

    result.best_reward = best_reward
    result.best_values = best_values
    result.best_containerfile = best_containerfile
    result.elapsed_seconds = time.time() - start_time
    if result.status == "budget_exhausted":
        logger.info("Budget exhausted for %s after %d iterations (best=%.4f)",
                     coordinate, result.iterations, best_reward)
    return result


def _build_initial_task(
    coordinate: str,
    findings: PrePassFindings,
    group_hints: list[dict],
) -> str:
    """Build the initial analysis task prompt."""
    sections = [
        f"Determine the complete build environment to reproduce the Maven Central artifact: {coordinate}\n",
        findings.to_prompt(),
    ]

    if group_hints:
        sections.append("\n## Cross-Package Hints (same group)")
        for hint in group_hints[:3]:
            sections.append(f"- {hint.get('coordinate', '?')}: template_id={hint.get('template_id', '?')}, "
                          f"build_system={hint.get('build_system', '?')}")

    sections.append(
        "\nOutput COMPLETE template values as a JSON object. "
        "Include ALL required fields."
    )
    return "\n".join(sections)


def _fallback_values_from_prepass(findings: PrePassFindings, coordinate: str) -> dict:
    """Create fallback template values from pre-pass findings when agent fails."""
    group_id, artifact_id, version = parse_gav(coordinate)
    return {
        "source_repo": findings.source_repo.value if findings.source_repo else "",
        "git_tag": findings.git_tag.value if findings.git_tag else f"v{version}",
        "jdk_version": findings.jdk_version.value if findings.jdk_version else "17",
        "jdk_minor_version": findings.jdk_minor_version.value if findings.jdk_minor_version else None,
        "jdk_distribution": findings.jdk_distribution.value if findings.jdk_distribution else "temurin",
        "build_command": findings.build_command.value if findings.build_command else "mvn clean install -B -DskipTests",
        "build_system": findings.build_system.value if findings.build_system else "maven",
        "maven_version": findings.maven_version.value if findings.maven_version else None,
        "build_tool_version": None,
        "base_image": findings.base_image.value if findings.base_image else None,
        "system_packages": [],
        "pre_build_commands": [],
        "post_build_commands": [],
        "config_files": [],
        "env_vars": {"SOURCE_DATE_EPOCH": "0"},
        "template_id": None,
        "module_path": findings.module_path.value if findings.module_path else None,
        "artifact_path_pattern": None,
        "use_maven_wrapper": (findings.use_maven_wrapper.value if findings.use_maven_wrapper else False),
        "confidence_notes": "Fallback from pre-pass — agent failed",
    }


def _ensure_defaults(values: dict, findings: PrePassFindings) -> dict:
    """Ensure critical default values are present."""
    if not values.get("env_vars"):
        values["env_vars"] = {}
    if "SOURCE_DATE_EPOCH" not in values["env_vars"]:
        values["env_vars"]["SOURCE_DATE_EPOCH"] = "0"
    if not values.get("system_packages"):
        values["system_packages"] = []
    if not values.get("pre_build_commands"):
        values["pre_build_commands"] = []
    if not values.get("post_build_commands"):
        values["post_build_commands"] = []
    if not values.get("config_files"):
        values["config_files"] = []
    if "use_maven_wrapper" not in values:
        values["use_maven_wrapper"] = False
    return values


def _hash_template_values(values: dict) -> str:
    """Hash template values for stagnation/oscillation detection."""
    import hashlib
    serializable = {k: v for k, v in sorted(values.items()) if k != "confidence_notes"}
    return hashlib.sha256(json.dumps(serializable, sort_keys=True, default=str).encode()).hexdigest()[:16]


def reverse_parse_containerfile(containerfile: str) -> dict:
    """Extract template values from an existing Containerfile via regex patterns.

    Used for warm-start: given a previously-working Containerfile, extract
    structured template values so the pipeline can start in feedback mode.
    """
    import re

    values: dict[str, Any] = {
        "source_repo": "",
        "git_tag": "",
        "jdk_version": "",
        "jdk_minor_version": None,
        "jdk_distribution": "temurin",
        "build_command": "",
        "build_system": "maven",
        "maven_version": None,
        "build_tool_version": None,
        "base_image": None,
        "system_packages": [],
        "pre_build_commands": [],
        "post_build_commands": [],
        "config_files": [],
        "env_vars": {},
        "template_id": None,
        "module_path": None,
        "artifact_path_pattern": None,
        "use_maven_wrapper": False,
        "confidence_notes": "Reverse-parsed from existing Containerfile",
    }

    from_match = re.search(r"^FROM\s+(.+)$", containerfile, re.MULTILINE)
    if from_match:
        image = from_match.group(1).strip()
        values["base_image"] = image
        if "temurin" in image:
            values["jdk_distribution"] = "temurin"
        elif "openjdk" in image:
            values["jdk_distribution"] = "openjdk"
        elif "corretto" in image:
            values["jdk_distribution"] = "corretto"
        version_m = re.search(r":(\d+(?:\.\d+\.\d+)?)", image)
        if version_m:
            ver = version_m.group(1)
            if "." in ver:
                values["jdk_minor_version"] = ver
                values["jdk_version"] = ver.split(".")[0]
            else:
                values["jdk_version"] = ver

    clone_match = re.search(
        r"git\s+clone\s+.*?--branch\s+'([^']+)'\s+'([^']+)'",
        containerfile,
    )
    if clone_match:
        values["git_tag"] = clone_match.group(1)
        values["source_repo"] = clone_match.group(2)

    env_matches = re.findall(r"^ENV\s+(\S+?)=(.+)$", containerfile, re.MULTILINE)
    for key, val in env_matches:
        values["env_vars"][key] = val.strip()

    maven_ver_match = re.search(
        r"apache-maven-(\d+\.\d+\.\d+)", containerfile,
    )
    if maven_ver_match:
        values["maven_version"] = maven_ver_match.group(1)

    run_lines = re.findall(r"^RUN\s+(.+)$", containerfile, re.MULTILINE)
    build_cmd = None
    for line in run_lines:
        if "mvn " in line or "./mvnw " in line or "gradle " in line or "./gradlew " in line or "ant " in line:
            if "apt-get" not in line and "install" not in line.lower().split("mvn")[0]:
                build_cmd = line.strip()
                break

    if build_cmd:
        values["build_command"] = build_cmd
        if "./mvnw" in build_cmd:
            values["use_maven_wrapper"] = True
            values["build_system"] = "maven"
        elif "mvn " in build_cmd:
            values["build_system"] = "maven"
        elif "gradlew" in build_cmd or "gradle " in build_cmd:
            values["build_system"] = "gradle"
        elif "ant " in build_cmd:
            values["build_system"] = "ant"

        pl_match = re.search(r"-pl\s+(\S+)", build_cmd)
        if pl_match:
            values["module_path"] = pl_match.group(1)

    return values


def _record_failed_approaches(
    failed_approaches: list[FailedApproach],
    prev_values: dict,
    current_values: dict,
    prev_reward: float,
    current_reward: float,
    iteration: int,
) -> None:
    """Record field-level changes as failed approaches when reward didn't improve."""
    if current_reward >= prev_reward:
        return

    for key in set(list(prev_values.keys()) + list(current_values.keys())):
        if key == "confidence_notes":
            continue
        old = prev_values.get(key)
        new = current_values.get(key)
        if old != new:
            failed_approaches.append(FailedApproach(
                what_changed=key,
                from_value=str(old),
                to_value=str(new),
                result=f"reward {prev_reward:.4f} → {current_reward:.4f}",
                why_it_failed=f"Regression of {prev_reward - current_reward:.4f}",
                iteration=iteration,
            ))
