---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-17
source: factory-archivist
---

# Strategy: Elitist Gate with Patience Counter — Issue #32

## CEO Verdict: PROCEED

### Approved Hypothesis

**H1 (FIX): Add elitist gate with patience counter to prevent containerfile regression**

- **Category**: FIX
- **Issue**: #32 — Elitist preservation broken within a single run
- **Target**: `src/buildroot/agent/loop.py` only (single file change)
- **Priority**: high

### Problem Statement

The inner loop tracks `best_reward` and `best_attempt` correctly (loop.py:129-131) but never uses them to prevent the active containerfile from regressing. All four mutation points (failure agents line 116, builder refine line 169, explore line 175, fresh_start line 187) blindly overwrite the working containerfile. Observed in production: jettison:1.5.4 reached L3 on iter 1, regressed to L1 on iter 2.

### Approved Implementation (6 steps)

1. Add `patience_counter` (int, starts at 0) tracking consecutive iterations below `best_reward`
2. After existing best-tracking code (lines 129-131): if `eval_result.reward < result.best_reward`, increment counter; if `>=`, reset to 0
3. Before builder invocation (before line 148): if `patience_counter >= 2` and `result.best_attempt` exists, restore `containerfile = result.best_attempt.containerfile`, reset counter, log restoration
4. Failure agent path (line 116) needs no gate — fires on t==0 when best_attempt is None
5. Zero additional `evaluator.evaluate()` calls — use existing evaluation at line 87
6. No changes to `evaluator.py`, `jar_comparator.py`, or any other file

### Expected Impact

- Eliminates multi-iteration regressions within a single run
- Packages reaching high reward levels (L3/L4) early retain that progress
- Conservatively +1-2 additional L4 solves on 31-package benchmark (+3-6% solve_rate)
- No risk of reducing exploration — patience=1 allows one exploratory step below best

### Anti-Patterns to Avoid

- Don't add extra evaluations per iteration (expensive SSH+podman ~2-5 min each)
- Don't gate every mutation individually (4x code vs single gate)
- Don't set patience=0 (kills exploration)
- Don't modify evaluator.py or jar_comparator.py (fixed surfaces)
- Don't implement RecipeStore/RECIPE_DIR (reverted with exp 10, not on mainline)

### Context

- Current baseline: 7/31 L4 (22.6%) on 31-package benchmark
- Last kept: exp 9 (node-scoped agents, 22.6%)
- Last reverted: exp 10 (agent architecture overhaul, 3.2% — early termination regression)
- CEO confirmed Pattern B (elitist preservation with patience counter) from external research
