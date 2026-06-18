"""Inner loop orchestrator — iterates Containerfile mutations until success or budget exhaustion."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from buildroot.agent import analyzer
from buildroot.agent.analyzer import AnalyzeAgent
from buildroot.agent.evaluator import Evaluator
from buildroot.agent.models import BuildAttempt, DeadEndEntry, ProgressSignal, RecipeStore

logger = logging.getLogger(__name__)


@dataclass
class LoopResult:
    coordinate: str = ""
    status: str = "budget_exhausted"
    best_reward: float = 0.0
    best_attempt: BuildAttempt | None = None
    attempts: list[BuildAttempt] = field(default_factory=list)
    dead_ends: list[DeadEndEntry] = field(default_factory=list)
    iterations: int = 0
    elapsed_seconds: float = 0.0
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "status": self.status,
            "best_reward": self.best_reward,
            "iterations": self.iterations,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "attempts": [a.to_dict() for a in self.attempts],
            "dead_ends": [d.to_dict() for d in self.dead_ends],
        }


def run_inner_loop(
    coordinate: str,
    *,
    max_iterations: int = 15,
    host: str = "rh-h100-01",
    model: str = "claude-opus-4-6",
    skip_deps: bool = True,
    meta_guidance: str | None = None,
    node_agents: bool = False,
    initial_containerfile: str | None = None,
) -> LoopResult:
    """Run the inner loop: Observer → [AnalyzeAgent → spec_overrides → re-observe → Evaluator]* → result."""
    if node_agents:
        return _run_agent_loop(
            coordinate,
            max_iterations=max_iterations,
            host=host,
            model=model,
            skip_deps=skip_deps,
            meta_guidance=meta_guidance,
            initial_containerfile=initial_containerfile,
        )
    return _run_standard_loop(
        coordinate,
        max_iterations=max_iterations,
        host=host,
        model=model,
        skip_deps=skip_deps,
        meta_guidance=meta_guidance,
    )


def _run_standard_loop(
    coordinate: str,
    *,
    max_iterations: int = 15,
    host: str = "rh-h100-01",
    model: str = "claude-opus-4-6",
    skip_deps: bool = True,
    meta_guidance: str | None = None,
) -> LoopResult:
    """Standard inner loop — uses AnalyzeAgent → spec_overrides → re-observe → template re-render."""
    from buildroot.agent.augmented_observer import AgentAugmentedObserver

    start_time = time.time()
    result = LoopResult(coordinate=coordinate)

    observer = AgentAugmentedObserver(skip_deps=skip_deps)
    evaluator = Evaluator(host=host)
    analyze_agent = AnalyzeAgent()
    progress = ProgressSignal()
    dead_ends: list[DeadEndEntry] = []
    spec_overrides: dict[str, Any] = {}

    logger.info("Starting standard loop for %s (max %d iterations)", coordinate, max_iterations)

    try:
        spec, containerfile = observer.observe(coordinate)
    except Exception as e:
        result.status = "observer_failed"
        result.error_message = str(e)
        result.elapsed_seconds = time.time() - start_time
        return result
    if not containerfile:
        result.status = "observer_failed"
        result.elapsed_seconds = time.time() - start_time
        return result

    logger.info("Observer produced initial Containerfile (%d bytes)", len(containerfile))

    patience_counter = 0
    error_history: list[str] = []
    previous_progress: analyzer.BuildProgress | None = None

    for t in range(max_iterations):
        logger.info("Iteration %d/%d for %s", t + 1, max_iterations, coordinate)

        eval_result = evaluator.evaluate(containerfile, coordinate)
        error_class = analyzer.classify_error(
            eval_result.error_summary, eval_result.build_log,
            diff_summary=eval_result.diff_summary,
        )
        attempt = BuildAttempt(
            containerfile=containerfile,
            reward=eval_result.reward,
            level_reached=eval_result.level_reached,
            error_class=error_class,
            build_log_summary=eval_result.error_summary[:500],
            diff_summary=eval_result.diff_summary,
        )
        result.attempts.append(attempt)
        result.iterations = t + 1

        logger.info(
            "  reward=%.2f level=%d error_class=%s",
            eval_result.reward, eval_result.level_reached, attempt.error_class,
        )

        if eval_result.reward > result.best_reward:
            result.best_reward = eval_result.reward
            result.best_attempt = attempt

        if eval_result.reward < result.best_reward:
            patience_counter += 1
        else:
            patience_counter = 0

        if eval_result.reward >= 0.98:
            logger.info("  Reward >= 0.98, running confirmation build...")
            confirm = evaluator.evaluate(containerfile, coordinate)
            if confirm.reward >= 0.98:
                result.status = "success"
                result.elapsed_seconds = time.time() - start_time
                result.dead_ends = dead_ends
                logger.info("Confirmed success for %s in %d iterations", coordinate, t + 1)
                return result
            else:
                logger.info("  Confirmation failed (reward=%.2f), continuing...", confirm.reward)

        if t >= max_iterations - 1:
            break

        if (
            patience_counter >= 2
            and result.best_attempt is not None
            and result.best_attempt.containerfile
        ):
            logger.info(
                "Elitist gate: restoring best containerfile (current=%.2f < best=%.2f, patience exhausted)",
                eval_result.reward, result.best_reward,
            )
            containerfile = result.best_attempt.containerfile
            patience_counter = 0

        mode = progress.update(eval_result.reward)
        analysis = analyzer.analyze(eval_result, dead_ends)
        error_history.append(analysis.error_class)

        remediation_context = analyzer.build_remediation_context(
            analysis, eval_result.build_log,
            error_history=error_history[-10:],
            previous_progress=previous_progress,
        )
        previous_progress = analysis.build_progress

        if analysis.is_fundamental_blocker:
            result.status = "fundamental_blocker"
            result.elapsed_seconds = time.time() - start_time
            result.dead_ends = dead_ends
            logger.info("Fundamental blocker for %s: %s", coordinate, analysis.error_class)
            return result

        analyzer.update_dead_ends(
            dead_ends,
            analysis.error_class,
            _describe_approach(containerfile),
            (eval_result.error_summary or '')[:200],
        )

        logger.info("  mode=%s, fix_suggestion=%s", mode, analysis.fix_suggestion[:80])

        build_results = [{
            "level_reached": eval_result.level_reached,
            "reward": eval_result.reward,
            "error_class": attempt.error_class,
            "error_summary": (eval_result.error_summary or '')[:500],
            "diff_summary": eval_result.diff_summary,
            "comparison_verdict": eval_result.comparison_verdict,
        }]

        analyze_result = analyze_agent.analyze_cycle(
            coordinate, build_results, t + 1, dead_ends,
            remediation_context=remediation_context,
            containerfile=containerfile,
            build_log=eval_result.build_log,
        )

        if analyze_result.spec_overrides:
            spec_overrides.update(analyze_result.spec_overrides)
            logger.info("AnalyzeAgent spec_overrides: %s", analyze_result.spec_overrides)

        if analyze_result.is_systemic:
            if analyze_result.spec_overrides:
                logger.info("AnalyzeAgent flagged systemic issue but provided spec_overrides — continuing: %s", analyze_result.root_cause)
            else:
                logger.info("AnalyzeAgent flagged systemic issue with no fix: %s", analyze_result.root_cause)
                result.status = "systemic_blocker"
                result.elapsed_seconds = time.time() - start_time
                result.dead_ends = dead_ends
                return result

        if spec_overrides:
            AgentAugmentedObserver._apply_spec_overrides(spec, spec_overrides)

        if mode == "meta_shift":
            if analyzer.all_exhausted(dead_ends):
                result.status = "all_exhausted"
                result.elapsed_seconds = time.time() - start_time
                result.dead_ends = dead_ends
                logger.info("All approaches exhausted for %s", coordinate)
                return result
            spec_overrides.clear()
            progress.reset()

        build_error_ctx = (
            f"Error class: {analysis.error_class}\n"
            f"Error: {(eval_result.error_summary or '')[:300]}"
        )
        try:
            variants = observer.observe_top_k(
                coordinate, k=3, spec_overrides=spec_overrides,
                build_error_context=build_error_ctx,
            )
            if variants and variants[0][1]:
                variants.append((spec, containerfile))
                spec, containerfile = _evaluate_candidates(
                    variants, evaluator, coordinate, result, dead_ends,
                )
                logger.info("Re-observed with spec_overrides, %d variants", len(variants))
                attempt.fix_applied = f"reobserve: {mode}"
        except Exception as e:
            logger.warning("Re-observe with spec_overrides failed: %s", e)
            attempt.fix_applied = f"reobserve_error: {e}"

    result.elapsed_seconds = time.time() - start_time
    result.dead_ends = dead_ends
    logger.info(
        "Budget exhausted for %s after %d iterations (best_reward=%.2f)",
        coordinate, max_iterations, result.best_reward,
    )
    return result


def _run_agent_loop(
    coordinate: str,
    *,
    max_iterations: int = 15,
    host: str = "rh-h100-01",
    model: str = "claude-opus-4-6",
    skip_deps: bool = True,
    meta_guidance: str | None = None,
    initial_containerfile: str | None = None,
) -> LoopResult:
    """Agent-augmented inner loop with Top-K builds, AnalyzeAgent, recipes, and spec overrides."""
    from buildroot.agent.augmented_observer import AgentAugmentedObserver

    start_time = time.time()
    result = LoopResult(coordinate=coordinate)

    observer = AgentAugmentedObserver(skip_deps=skip_deps)
    evaluator = Evaluator(host=host)
    analyze_agent = AnalyzeAgent()
    recipe_store = RecipeStore()
    progress = ProgressSignal()
    dead_ends: list[DeadEndEntry] = []
    spec_overrides: dict[str, Any] = {}

    # P3: Check recipe store — skip if already L4
    existing_level = recipe_store.best_level(coordinate)
    if existing_level >= 4:
        logger.info("Recipe store: %s already at L4, skipping", coordinate)
        existing_cf = recipe_store.get_containerfile(coordinate, 4)
        if existing_cf:
            result.status = "recipe_skip"
            result.best_reward = 1.0
            result.best_attempt = BuildAttempt(containerfile=existing_cf, reward=1.0, level_reached=4)
            result.elapsed_seconds = time.time() - start_time
            return result

    # Seed recipe store from initial_containerfile if provided
    if initial_containerfile:
        recipe_store.save(coordinate, 3, initial_containerfile, 0.5)
        logger.info("Seeded RecipeStore with initial_containerfile for %s", coordinate)

    # Warm-start: use best known Containerfile as a seed candidate
    warm_start_cf = None
    if existing_level >= 2:
        warm_start_cf = recipe_store.get_containerfile(coordinate, existing_level)
        if warm_start_cf:
            logger.info("Warm-start from RecipeStore: L%d Containerfile for %s", existing_level, coordinate)

    logger.info(
        "Starting agent loop for %s (max %d iterations, existing_level=L%d, warm_start=%s)",
        coordinate, max_iterations, existing_level, warm_start_cf is not None,
    )

    # Initial observation with Top-K
    try:
        variants = observer.observe_top_k(coordinate, k=3, spec_overrides=spec_overrides)
    except Exception as e:
        if warm_start_cf:
            logger.warning("Observer failed but using warm-start Containerfile: %s", e)
            from buildroot.agent.observer import Observer
            obs = Observer(skip_deps=skip_deps)
            spec_fallback, _ = obs.observe(coordinate)
            variants = [(spec_fallback, warm_start_cf)]
        else:
            result.status = "observer_failed"
            result.error_message = str(e)
            result.elapsed_seconds = time.time() - start_time
            return result

    if not variants or not variants[0][1]:
        if warm_start_cf:
            from buildroot.agent.observer import Observer
            obs = Observer(skip_deps=skip_deps)
            spec_fallback, _ = obs.observe(coordinate)
            variants = [(spec_fallback, warm_start_cf)]
        else:
            result.status = "observer_failed"
            result.elapsed_seconds = time.time() - start_time
            return result

    # Insert warm-start as first candidate if available
    if warm_start_cf and variants:
        variants.insert(0, (variants[0][0], warm_start_cf))

    # Evaluate all K candidates, pick best
    spec, containerfile = _evaluate_candidates(variants, evaluator, coordinate, result, dead_ends)
    logger.info("Initial observation produced %d variants, best selected", len(variants))

    patience_counter = 0
    error_history: list[str] = []
    previous_progress: analyzer.BuildProgress | None = None

    for t in range(max_iterations):
        logger.info("Iteration %d/%d for %s", t + 1, max_iterations, coordinate)

        eval_result = evaluator.evaluate(containerfile, coordinate)
        error_class = analyzer.classify_error(
            eval_result.error_summary, eval_result.build_log,
            diff_summary=eval_result.diff_summary,
        )
        attempt = BuildAttempt(
            containerfile=containerfile,
            reward=eval_result.reward,
            level_reached=eval_result.level_reached,
            error_class=error_class,
            build_log_summary=eval_result.error_summary[:500],
            diff_summary=eval_result.diff_summary,
        )
        result.attempts.append(attempt)
        result.iterations = t + 1

        logger.info(
            "  reward=%.2f level=%d error_class=%s",
            eval_result.reward, eval_result.level_reached, attempt.error_class,
        )

        if eval_result.reward > result.best_reward:
            result.best_reward = eval_result.reward
            result.best_attempt = attempt
            patience_counter = 0
        elif eval_result.reward < result.best_reward:
            patience_counter += 1

        # P3: Save recipe at each level reached
        if eval_result.level_reached > 0:
            recipe_store.save(coordinate, eval_result.level_reached, containerfile, eval_result.reward)

        if eval_result.reward >= 0.98:
            logger.info("  Reward >= 0.98, running confirmation build...")
            confirm = evaluator.evaluate(containerfile, coordinate)
            if confirm.reward >= 0.98:
                result.status = "success"
                result.elapsed_seconds = time.time() - start_time
                result.dead_ends = dead_ends
                recipe_store.save(coordinate, confirm.level_reached, containerfile, confirm.reward)
                logger.info("Confirmed success for %s in %d iterations", coordinate, t + 1)
                return result
            else:
                logger.info("  Confirmation failed (reward=%.2f), continuing...", confirm.reward)

        if t >= max_iterations - 1:
            break

        if (
            patience_counter >= 2
            and result.best_attempt is not None
            and result.best_attempt.containerfile
        ):
            logger.info(
                "Elitist gate: restoring best containerfile (current=%.2f < best=%.2f, patience exhausted)",
                eval_result.reward, result.best_reward,
            )
            containerfile = result.best_attempt.containerfile
            patience_counter = 0

        mode = progress.update(eval_result.reward)
        analysis = analyzer.analyze(eval_result, dead_ends)
        error_history.append(analysis.error_class)

        remediation_context = analyzer.build_remediation_context(
            analysis, eval_result.build_log,
            error_history=error_history[-10:],
            previous_progress=previous_progress,
        )
        previous_progress = analysis.build_progress

        if analysis.is_fundamental_blocker:
            result.status = "fundamental_blocker"
            result.elapsed_seconds = time.time() - start_time
            result.dead_ends = dead_ends
            return result

        analyzer.update_dead_ends(
            dead_ends,
            analysis.error_class,
            _describe_approach(containerfile),
            (eval_result.error_summary or '')[:200],
        )

        # Run AnalyzeAgent after each failed iteration
        build_results = [{
            "level_reached": eval_result.level_reached,
            "reward": eval_result.reward,
            "error_class": attempt.error_class,
            "error_summary": (eval_result.error_summary or '')[:500],
            "diff_summary": eval_result.diff_summary,
            "comparison_verdict": eval_result.comparison_verdict,
        }]

        analyze_result = analyze_agent.analyze_cycle(
            coordinate, build_results, t + 1, dead_ends,
            remediation_context=remediation_context,
            containerfile=containerfile,
            build_log=eval_result.build_log,
        )

        if analyze_result.spec_overrides:
            spec_overrides.update(analyze_result.spec_overrides)
            logger.info("AnalyzeAgent spec_overrides: %s", analyze_result.spec_overrides)

        if spec_overrides:
            from buildroot.agent.augmented_observer import AgentAugmentedObserver
            AgentAugmentedObserver._apply_spec_overrides(spec, spec_overrides)

        if analyze_result.is_systemic:
            if analyze_result.spec_overrides:
                logger.info("AnalyzeAgent flagged systemic issue but provided spec_overrides — continuing: %s", analyze_result.root_cause)
            else:
                logger.info("AnalyzeAgent flagged systemic issue with no fix: %s", analyze_result.root_cause)
                result.status = "systemic_blocker"
                result.elapsed_seconds = time.time() - start_time
                result.dead_ends = dead_ends
                return result

        # Re-observe with accumulated spec_overrides → template re-render
        build_error_ctx = (
            f"Error class: {analysis.error_class}\n"
            f"Error: {(eval_result.error_summary or '')[:300]}"
        )
        if spec_overrides:
            try:
                variants = observer.observe_top_k(
                    coordinate, k=3, spec_overrides=spec_overrides,
                    build_error_context=build_error_ctx,
                )
                if variants and variants[0][1]:
                    variants.append((spec, containerfile))
                    spec, containerfile = _evaluate_candidates(
                        variants, evaluator, coordinate, result, dead_ends,
                    )
                    logger.info("Re-observed with spec_overrides, %d variants", len(variants))
            except Exception as e:
                logger.warning("Re-observe with spec_overrides failed: %s", e)

        logger.info("  mode=%s, fix_suggestion=%s", mode, analysis.fix_suggestion[:80])

        if mode == "meta_shift":
            if analyzer.all_exhausted(dead_ends):
                result.status = "all_exhausted"
                result.elapsed_seconds = time.time() - start_time
                result.dead_ends = dead_ends
                return result
            spec_overrides.clear()
            progress.reset()
        attempt.fix_applied = f"reobserve: {mode}"

    result.elapsed_seconds = time.time() - start_time
    result.dead_ends = dead_ends
    logger.info(
        "Budget exhausted for %s after %d iterations (best_reward=%.2f)",
        coordinate, max_iterations, result.best_reward,
    )
    return result


def _evaluate_candidates(
    variants: list[tuple],
    evaluator: Evaluator,
    coordinate: str,
    result: LoopResult,
    dead_ends: list[DeadEndEntry],
) -> tuple:
    """Evaluate K candidate (spec, containerfile) pairs, return the best one."""
    if len(variants) == 1:
        return variants[0]

    best_spec, best_cf = variants[0]
    best_reward = -1.0

    for spec_v, cf_v in variants:
        if not cf_v:
            continue
        eval_r = evaluator.evaluate(cf_v, coordinate)
        attempt = BuildAttempt(
            containerfile=cf_v,
            reward=eval_r.reward,
            level_reached=eval_r.level_reached,
            error_class=analyzer.classify_error(eval_r.error_summary, eval_r.build_log),
            build_log_summary=eval_r.error_summary[:500],
            fix_applied="top_k_candidate",
        )
        result.attempts.append(attempt)

        if eval_r.reward > best_reward:
            best_reward = eval_r.reward
            best_spec = spec_v
            best_cf = cf_v
            if eval_r.reward > result.best_reward:
                result.best_reward = eval_r.reward
                result.best_attempt = attempt
        else:
            analyzer.update_dead_ends(
                dead_ends,
                attempt.error_class,
                _describe_approach(cf_v),
                eval_r.error_summary[:200],
            )

    return best_spec, best_cf


def _describe_approach(containerfile: str) -> str:
    """Extract a rich description of the current approach from the Containerfile."""
    return analyzer.extract_build_signature(containerfile)
