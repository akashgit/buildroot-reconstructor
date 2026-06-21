---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 10
verdict: REVERT
score_delta: -0.194
date: 2026-06-17
source: factory-archivist
---

# Experiment #010: Agent architecture overhaul — AnalyzeAgent, Top-K builds, tiered recipes, spec overrides, Podman prefix, reproducible flags

## Hypothesis
Overhaul the agent architecture to address 5 structural gaps identified in experiment #009's 22.6% L4 rate. Six implementation priorities (P1-P6) target the gap between node-scoped agents firing correctly and builds actually succeeding: agents lack failure feedback (P2), explore one path at a time (P1), don't persist fixes (P3/P4), and miss two universal build issues — Podman short-name resolution (P5) and non-reproducible metadata (P6). Target: L4 22.6% -> >=35% (11/31).

## Result
**REVERT** — score changed from 22.6% L4 (7/31) to 3.2% L4 (1/31). SEVERE REGRESSION of -19.4 percentage points.

### Benchmark Results
| Metric | Baseline (exp 9) | Exp 10 | Delta |
|--------|-------------------|--------|-------|
| L4 packages | 7/31 | 1/31 | -6 |
| L4 rate | 22.6% | 3.2% | -19.4pp |
| Target | — | ≥35% (11/31) | MISSED |
| Packages regressed | — | 14/31 | — |
| Packages improved | — | 4/31 | — |
| Packages unchanged | — | 13/31 | — |

### Package-Level Regressions (14 packages)
- jackson-databind L4→L3, avro L4→L1, snakeyaml L4→L1, snappy-java L4→L1
- Multiple L4→L1 and L3→L1 regressions caused by premature iteration termination

### Package-Level Improvements (4 packages)
- commons-lang3 L1→L3, json-path L1→L3, junit L1→L3, logback-classic L1→L2

## Root Cause Analysis
**Early termination logic at `loop.py:300-315` is fatally aggressive.**

The `consecutive_no_improvement >= 3` threshold terminates packages after ~4 iterations when the baseline ran all 15 iterations. The termination counter tracks level improvement only (not reward), so packages stuck at L1 that need many attempts to break through L2/L3/L4 get terminated prematurely.

- Packages that previously reached L4 in 8-12 iterations now terminate at iteration 4
- The AnalyzeAgent itself worked when it fired — the issue is not the analysis but the iteration budget
- The strategy spec warned about early termination but the threshold was set too low

## What Worked
| Priority | Assessment |
|----------|-----------|
| P5 (Podman prefix) | **WORKED** — Fixed docker.io/library/ prefix issue universally |
| P2 (AnalyzeAgent) | **WORKED WHEN FIRED** — Produced structured diagnosis, but too few iterations to matter |
| P1 (Top-K candidates) | **WORKED** — Generated multiple candidates correctly |
| P3/P4 (Recipes/Overrides) | **NOT TESTED** — Too few iterations to accumulate meaningful overrides |
| P6 (Reproducible flags) | **UNKNOWN** — Very few packages reached L3+ to test metadata normalization |

## What Failed
- **Early termination threshold of 3 is catastrophically aggressive** — should be ≥8 or removed entirely
- **Level-only tracking misses reward improvement** — a package improving from 0.05 to 0.14 within L1 registers as "no improvement"
- **Baseline's budget-exhaustion approach (15 iterations) outperforms aggressive early termination** — the exploration budget matters more than smart termination

## Key Lesson
The strategy spec itself warned about early termination ('Don't fire AnalyzeAgent without early termination') but the threshold was set too low. A threshold of 3 with only level-based tracking (not reward-based) meant packages stuck at L1 that need many attempts to break through L2/L3/L4 get terminated prematurely. The baseline's budget exhaustion approach (run all 15 iterations) is more effective than aggressive early termination.

## Recommendation for Next Cycle
1. **Remove early termination entirely**, OR raise threshold to ≥8 consecutive no-improvement
2. **Track reward improvement, not just level** — reward is a finer-grained signal than level
3. **Preserve P5 (Podman prefix)** — this fix is universally beneficial and should be cherry-picked
4. **Retest with full 15-iteration budget** before concluding whether P1/P2/P3/P4 have value

## CEO Code Quality Review (Pre-Benchmark)
**ISSUES_FOUND: 2** — CEO proceeded despite issues.

1. **[Redundancy]** `loop.py`: `_evaluate_candidates` evaluates K candidates, then the for-loop immediately re-evaluates the winner.
2. **[Missing tests]** No unit tests for `AnalyzeAgent`, `RecipeStore`, `observe_top_k`, `_run_agent_loop`, or `_evaluate_candidates`.

## What Changed
**PR #29** (CLOSED — reverted) — `feat: agent architecture overhaul — AnalyzeAgent, Top-K builds, tiered recipes, spec overrides, Podman prefix, reproducible flags`
- **Branch**: `factory/run-65e04373`
- **Issue**: #27
- **Files**: 13 changed (+715/-47)

### Six Implementation Priorities

| Priority | Description | Implementation |
|----------|-------------|----------------|
| P1 | Top-K parallel candidate builds | `apply_top_k()` in `base.py` forks spec K times; `observe_top_k()` renders K Containerfiles; `_evaluate_candidates()` evaluates all K, keeps winner |
| P2 | AnalyzeAgent | Claude Code subprocess ($2 budget, 300s timeout); diagnoses root cause; writes append-only DO/DON'T playbook; returns `spec_overrides`; early termination after ≥3 consecutive stalled iterations |
| P3 | Tiered recipe store | `RecipeStore` saves recipes at every successful level (L2-L4); future runs skip solved packages |
| P4 | Spec overrides persistence | `spec_overrides` dict accumulates AnalyzeAgent suggestions across iterations |
| P5 | Podman registry prefix | `_map_distribution_to_image()` adds `docker.io/library/` for root Docker Hub images AND `docker.io/` for org-scoped images |
| P6 | Reproducible build flags | `-Dproject.build.outputTimestamp=1` for all Maven commands; post-build JAR normalization |

## Links
- Project: buildroot-reconstructor
- Issue: #27
- PR: #29 (CLOSED)
- Strategy: strategies/buildroot-reconstructor-2026-06-16-agent-architecture-overhaul.md
- Previous: experiments/buildroot-reconstructor-009.md
