---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-17
source: factory-archivist
---

# Cycle Summary: Experiment #010 — Agent Architecture Overhaul (REVERT)

## Cycle Overview
- **Mode**: Improve (targeted)
- **Issue**: #27 — Agent architecture: feedback loops, multi-candidate builds, runtime awareness
- **Hypothesis**: H1 — Agent architecture overhaul (mixed: code + operational benchmark)
- **Verdict**: **REVERT** — L4 solve rate regressed from 22.6% (7/31) to 3.2% (1/31)
- **Score Delta**: -19.4 percentage points on L4 rate
- **Significance**: First revert in 10 experiments. Broke 9-experiment keep streak.

## What Happened

Six architecture priorities (P1-P6) were implemented in a single PR (#29, +715/-47 lines, 13 files):

| Priority | Description | Outcome |
|----------|-------------|---------|
| P1 | Top-K parallel candidate builds | Worked correctly, insufficient iterations to exploit |
| P2 | AnalyzeAgent with ACE playbooks | Worked when fired, but early termination killed iteration budget |
| P3 | Tiered recipe store | Not tested — too few iterations to accumulate recipes |
| P4 | Spec overrides persistence | Not tested — too few iterations |
| P5 | Podman registry prefix fix | **Worked** — universally beneficial, should be cherry-picked |
| P6 | Reproducible build flags | Unknown — too few packages reached L3+ |

## Root Cause

Early termination logic at `loop.py:300-315` (`consecutive_no_improvement >= 3`) was catastrophically aggressive:
- Baseline ran all 15 iterations per package
- Experiment #010 terminated packages after ~4 iterations
- Termination tracked level (discrete) not reward (continuous), missing within-level progress
- Packages that solved at iteration 8-12 in baseline were killed at iteration 4

## Quantitative Impact

| Metric | Baseline (exp 9) | Exp 10 | Delta |
|--------|-------------------|--------|-------|
| L4 packages | 7/31 | 1/31 | -6 |
| L4 rate | 22.6% | 3.2% | -19.4pp |
| Packages regressed | — | 14/31 | — |
| Packages improved | — | 4/31 | — |
| Packages unchanged | — | 13/31 | — |

## Key Learnings (3 new patterns archived)

1. **Early termination must be calibrated against baseline iteration counts** — Set threshold at ≥75th percentile of successful iteration counts, not by intuition. If most L4 solves happen at iteration 8-12, threshold of 3 is catastrophic.

2. **Level-based tracking is too coarse for termination** — A 3x reward improvement within L1 (0.05→0.14) was invisible to level-only tracking. Track the finest-grained signal available.

3. **Long keep streaks foster overconfidence** — Code review passed cleanly; the regression was only visible via full 31-package benchmark. For changes that alter loop control flow, the benchmark IS the gate.

## Recommendations for Next Cycle

1. Remove early termination entirely, OR raise threshold to ≥8 with reward-based tracking
2. Cherry-pick P5 (Podman prefix) as a standalone fix — universally beneficial
3. Retest P1/P2/P3/P4 with full 15-iteration budget before concluding they lack value
4. The 4 improved packages (commons-lang3, json-path, junit, logback-classic) suggest the architecture has merit when given sufficient iterations

## Project State After Revert

- **Score**: ~0.845 (unchanged — reverted to exp #009 state)
- **Keep Streak**: 0 (reset from 9)
- **Total Experiments**: 10 (9 kept, 1 reverted)
- **Branch**: factory/run-65e04373 (reverted, PR #29 closed)
- **Codebase**: Back to exp #009 state on main branch
