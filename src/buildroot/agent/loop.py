"""Inner loop orchestrator — delegates to pipeline v3."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from buildroot.agent.models import BuildAttempt, DeadEndEntry

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
    node_agents: bool = False,
    initial_containerfile: str | None = None,
    pipeline: str = "v1",
) -> LoopResult:
    """Run the inner loop — delegates to pipeline v3."""
    from buildroot.agent.pipeline_v3 import run_v3_pipeline

    v3_result = run_v3_pipeline(
        coordinate,
        max_iterations=max_iterations,
        host=host,
        skip_deps=skip_deps,
        warm_start_containerfile=initial_containerfile,
    )
    return LoopResult(
        coordinate=v3_result.coordinate,
        status=v3_result.status,
        best_reward=v3_result.best_reward,
        iterations=v3_result.iterations,
        elapsed_seconds=v3_result.elapsed_seconds,
        error_message=v3_result.error_message,
    )
