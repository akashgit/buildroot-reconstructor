"""Data models for the agentic reconstruction loop."""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field


@dataclass
class BuildAttempt:
    """A single iteration's build attempt and its evaluation result."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: str | None = None
    containerfile: str = ""
    reward: float = 0.0
    level_reached: int = 0
    error_class: str = ""
    build_log_summary: str = ""
    diff_summary: str = ""
    fix_applied: str = ""
    q_value: float = 0.0
    n_expansions: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "reward": self.reward,
            "level_reached": self.level_reached,
            "error_class": self.error_class,
            "build_log_summary": self.build_log_summary,
            "diff_summary": self.diff_summary,
            "fix_applied": self.fix_applied,
            "timestamp": self.timestamp,
        }


@dataclass
class DeadEndEntry:
    """An approach that has been tried and failed enough times to be marked exhausted."""

    error_class: str
    approach: str
    failure_count: int = 0
    threshold: int = 2
    examples: list[str] = field(default_factory=list)

    @property
    def is_exhausted(self) -> bool:
        return self.failure_count >= self.threshold

    def record_failure(self, log_summary: str) -> None:
        self.failure_count += 1
        if len(self.examples) < 3:
            self.examples.append(log_summary[:200])

    def to_dict(self) -> dict:
        return {
            "error_class": self.error_class,
            "approach": self.approach,
            "failure_count": self.failure_count,
            "threshold": self.threshold,
            "is_exhausted": self.is_exhausted,
            "examples": self.examples,
        }


@dataclass
class EvalResult:
    """Result from the 4-level evaluation pipeline."""

    l1_parse: bool = False
    l2_build: bool = False
    l3_command: bool = False
    l4_match: bool = False
    reward: float = 0.0
    build_log: str = ""
    error_summary: str = ""
    comparison_verdict: str = ""
    level_reached: int = 0

    def compute_reward(self) -> float:
        self.reward = (
            0.05 * float(self.l1_parse)
            + 0.10 * float(self.l2_build)
            + 0.35 * float(self.l3_command)
            + 0.50 * float(self.l4_match)
        )
        self.level_reached = (
            4 if self.l4_match
            else 3 if self.l3_command
            else 2 if self.l2_build
            else 1 if self.l1_parse
            else 0
        )
        return self.reward

    def to_dict(self) -> dict:
        return {
            "l1_parse": self.l1_parse,
            "l2_build": self.l2_build,
            "l3_command": self.l3_command,
            "l4_match": self.l4_match,
            "reward": self.reward,
            "level_reached": self.level_reached,
            "error_summary": self.error_summary,
            "comparison_verdict": self.comparison_verdict,
        }


class ProgressSignal:
    """AdaEvolve G_t exponential-decay signal for exploit/explore/meta-shift mode switching.

    G_t tracks marginal improvement. High G_t = making progress (exploit).
    Low G_t = stagnating (explore). Very low G_t = exhausted (meta-shift).
    """

    def __init__(self, rho: float = 0.9, tau_m: float = 0.12, tau_s: float = 0.02):
        self.g_t: float = 1.0
        self.best_reward: float = 0.0
        self.rho = rho
        self.tau_m = tau_m
        self.tau_s = tau_s

    def update(self, new_reward: float) -> str:
        delta = max(0, new_reward - self.best_reward) / max(self.best_reward, 1e-6)
        self.g_t = self.rho * self.g_t + (1 - self.rho) * delta ** 2
        self.best_reward = max(self.best_reward, new_reward)
        if self.g_t > self.tau_m:
            return "exploit"
        elif self.g_t > self.tau_s:
            return "explore"
        else:
            return "meta_shift"

    def reset(self) -> None:
        self.g_t = 1.0
        self.best_reward = 0.0
