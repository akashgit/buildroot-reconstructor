---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - outer-loop
source: factory-archivist
date: 2026-06-13
---

# AdaEvolve: Hierarchical Adaptive Optimization for Outer Loop

**Source**: [AdaEvolve: Adaptive LLM Driven Zeroth-Order Optimization](https://arxiv.org/abs/2602.20133)

## Key Findings for Outer Loop

### J(S) Strategy Scoring Formula
`J = (s_end - s_start) · log(1 + s_start) / √W` — the log term upweights improvements from higher baselines (harder to improve when already good). W is window size. Directly specified in the outer loop spec.

### Three-Level Adaptation Hierarchy
1. **Level 1 (local)**: Exploration intensity modulation per iteration — **already implemented** as G_t exploit/explore/meta_shift in the inner loop
2. **Level 2 (global)**: UCB bandit for resource allocation across populations — maps to **package scheduling** in the outer loop (which packages get more inner-loop budget)
3. **Level 3 (meta)**: When G_t ≤ τ_M for ALL populations, trigger strategy-level changes — maps to the **Outer Strategist** proposing code changes to the reconstructor itself

### Stagnation Thresholds (fixed across 185 problems)
- τ_M = 0.12 (meta-guidance trigger)
- τ_S = 0.02 (spawn new populations)
- Inner loop already uses these. Outer loop should apply analogous thresholds on solve_rate stagnation.

### Dynamic Island Spawning
When all islands stagnate, spawn a new island with a random seed from the archive. For outer loop: if all strategies stagnate, try an entirely different approach (e.g., switch from per-package repair to template-based generation).

## Implementation Relevance
J(S) formula is straightforward to compute. Three-level hierarchy maps cleanly: Level 1 = inner loop (exists), Level 2 = package scheduling (out of scope per spec), Level 3 = outer loop code changes (the main deliverable).
