"""Inner loop orchestrator — iterates Containerfile mutations until success or budget exhaustion."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from buildroot.agent import analyzer
from buildroot.agent.builder import Builder
from buildroot.agent.evaluator import Evaluator
from buildroot.agent.models import BuildAttempt, DeadEndEntry, ProgressSignal
from buildroot.agent.observer import Observer

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
) -> LoopResult:
    """Run the inner loop: Observer → [Builder → Evaluator → Analyzer]* → result."""
    start_time = time.time()
    result = LoopResult(coordinate=coordinate)

    if node_agents:
        from buildroot.agent.augmented_observer import AgentAugmentedObserver
        observer = AgentAugmentedObserver(skip_deps=skip_deps)
    else:
        observer = Observer(skip_deps=skip_deps)
    builder = Builder(model=model, meta_guidance=meta_guidance)
    evaluator = Evaluator(host=host)
    progress = ProgressSignal()
    dead_ends: list[DeadEndEntry] = []

    logger.info("Starting inner loop for %s (max %d iterations, node_agents=%s)", coordinate, max_iterations, node_agents)

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

    failure_agent_used = False

    for t in range(max_iterations):
        logger.info("Iteration %d/%d for %s", t + 1, max_iterations, coordinate)

        eval_result = evaluator.evaluate(containerfile, coordinate)
        attempt = BuildAttempt(
            containerfile=containerfile,
            reward=eval_result.reward,
            level_reached=eval_result.level_reached,
            error_class=analyzer.classify_error(
                eval_result.error_summary, eval_result.build_log
            ),
            build_log_summary=eval_result.error_summary[:500],
            diff_summary=eval_result.diff_summary,
        )
        result.attempts.append(attempt)
        result.iterations = t + 1

        if (
            node_agents
            and not failure_agent_used
            and t == 0
            and eval_result.level_reached < 4
            and hasattr(observer, "run_failure_agents")
        ):
            failure_result = observer.run_failure_agents(
                spec, containerfile,
                level_reached=eval_result.level_reached,
                build_log=eval_result.build_log,
                diff_summary=eval_result.diff_summary,
                comparison_verdict=eval_result.comparison_verdict,
            )
            if failure_result:
                spec, containerfile = failure_result
                attempt.fix_applied = "failure_agent_fix"
                failure_agent_used = True
                logger.info(
                    "  reward=%.2f level=%d error_class=%s (failure_agent activated)",
                    eval_result.reward, eval_result.level_reached, attempt.error_class,
                )
                if eval_result.reward > result.best_reward:
                    result.best_reward = eval_result.reward
                    result.best_attempt = attempt
                continue

        logger.info(
            "  reward=%.2f level=%d error_class=%s",
            eval_result.reward, eval_result.level_reached, attempt.error_class,
        )

        if eval_result.reward > result.best_reward:
            result.best_reward = eval_result.reward
            result.best_attempt = attempt

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

        mode = progress.update(eval_result.reward)
        analysis = analyzer.analyze(eval_result, dead_ends)

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
            eval_result.error_summary[:200],
        )

        logger.info("  mode=%s, fix_suggestion=%s", mode, analysis.fix_suggestion[:80])

        try:
            if mode == "exploit":
                containerfile = builder.refine(
                    containerfile, analysis.error_class,
                    eval_result.error_summary, dead_ends, spec,
                )
                attempt.fix_applied = f"refine: {analysis.fix_suggestion[:100]}"
            elif mode == "explore":
                containerfile = builder.explore(
                    containerfile, spec, analysis.error_class,
                    eval_result.error_summary, dead_ends,
                )
                attempt.fix_applied = "explore: trying different approach"
            else:
                if analyzer.all_exhausted(dead_ends):
                    result.status = "all_exhausted"
                    result.elapsed_seconds = time.time() - start_time
                    result.dead_ends = dead_ends
                    logger.info("All approaches exhausted for %s", coordinate)
                    return result
                containerfile = builder.fresh_start(spec)
                attempt.fix_applied = "meta_shift: fresh start from metadata"
                progress.reset()
        except Exception as e:
            logger.error("Builder error at iteration %d: %s", t + 1, e)
            attempt.fix_applied = f"builder_error: {e}"
            continue

    result.elapsed_seconds = time.time() - start_time
    result.dead_ends = dead_ends
    logger.info(
        "Budget exhausted for %s after %d iterations (best_reward=%.2f)",
        coordinate, max_iterations, result.best_reward,
    )
    return result


def _describe_approach(containerfile: str) -> str:
    """Extract a short description of the current approach from the Containerfile."""
    lines = containerfile.splitlines()
    from_line = ""
    build_cmd = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FROM ") and not from_line:
            from_line = stripped[:80]
        if stripped.startswith("RUN ") and ("mvn " in stripped or "maven" in stripped.lower()):
            build_cmd = stripped[:80]
    return f"{from_line} | {build_cmd}" if from_line else "unknown approach"
