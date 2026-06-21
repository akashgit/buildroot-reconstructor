---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-18
source: factory-archivist
run_id: run-e8d140d9
ceo_verdict: PROCEED
---

# Strategy: buildroot-reconstructor — 2026-06-18

## Cycle Context

- **Run ID**: run-e8d140d9
- **Target**: Issue #42 (targeted mode — single hypothesis)
- **Current Score**: 0.6814 (composite), 0.7948 (benchmark post-exp-13)
- **Weakest Dimension**: capability_surface (0.3837)
- **Last 3 Experiments**: #012 KEEP (+0.025), #013 KEEP (+0.2900), #014 KEEP (delta n/a)
- **Keep Streak**: 3 consecutive keeps

## Design Space Assessment

| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | Core pipeline, 4-level eval, node agents, agentic loops all built |
| Bug fixes | 4 | Exp 12-14 fixed elitist gate, allowed_tools, 8 critique items |
| Instrumentation | 2 | 62.7% observability score, only 20% function coverage |
| Flow changes | 3 | Inner/outer loops, agent-augmented observer, top-k candidates |
| New agents | 4 | 13 node agents, AnalyzeAgent, failure agents, outer strategist |
| Prompt engineering | 2 | Node agent prompts tuned once (exp 9), AnalyzeAgent prompt untouched since exp 10 |
| Eval improvements | 3 | L1-L4 pipeline complete, continuous scoring, but guard_patterns failing |
| Knowledge management | 2 | Dead-end registry exists but coarse-grained, recipe store not implemented |
| Infrastructure | 3 | Multi-node SSH deployment, warm-start, resume flag |
| Operational execution | 3 | 31-pkg benchmark run, mini-benchmark defined, but no recent full run |
| Self-evolution | 1 | No factory meta-learning, no self-analysis beyond outer strategist |

**Underserved**: Self-evolution, Instrumentation, Prompt engineering

## Approved Hypothesis

### H1: Remove Builder agent, add controlled template modification to AnalyzeAgent (EXPLOIT)

**Backlog item**: Issue #42, also addresses #22, #24

**What**: Implement all 11 required changes from issue #42:

1. Relocate `sanitize_gha_expressions()` from `builder.py` to `analyzer.py` (evaluator.py imports it)
2. Delete `builder.py` entirely (595 lines)
3. Remove Builder from `loop.py`: strip import, instantiation, and invocation blocks
4. Expand AnalyzeAgent `spec_overrides` vocabulary with 3 tiers of new fields
5. Add new fields to `BuildrootSpec` in `pipeline/models.py`
6. Extend `_apply_spec_overrides()` in `augmented_observer.py`
7. Add template injection points to all 4 templates
8. Wire template selection overrides in `containerfile.py`
9. Fix L4 error classification (pass `diff_summary` to `classify_error()`)
10. Upgrade AnalyzeAgent model from `claude-sonnet-4-6` to `claude-opus-4-6`
11. Add `--legacy-builder` CLI flag for fallback
12. Clean up references in outer_strategist.py, guards.py, evaluator.py

**Why**: Builder is empirically net-zero (7 improvements = 7 regressions), consumed 89% of iterations ($2-5/opus call each), never achieved L4. AnalyzeAgent concept validated in exp 10 (failure was early termination, not the agent). Re-observe flow already exists at loop.py:430-440. All 5 L3 packages need reproducibility parameters — structured spec_overrides, not Containerfile rewriting.

**Expected impact**: experiment_diversity +0.05, factory_effectiveness +0.02. No immediate L4 score improvement — the refactor enables future L4 gains by giving AnalyzeAgent the right levers.

## CEO Verdict

**PROCEED** — approved 2026-06-18

### CEO Assessment
- Specificity: Excellent — all 12 change items have exact file names, line numbers, implementation details
- Scope: One PR's worth — large but coherent, single architectural purpose
- Expected impact: Realistic — no immediate L4 claim, correctly frames as enabling infrastructure
- FEEC priority: EXPLOIT — correct, exploiting known weakness
- Targeted mode compliance: Exactly 1 hypothesis

### Key Risks Noted
- 11 files modified in one PR — large surface area but coherent
- Template injection points must be tested across all 4 templates
- evaluator.py import path must be updated for `sanitize_gha_expressions`
- `_run_standard_loop` changes need care — it's the fallback loop

## Anti-patterns to Avoid

- **Exp 10 early termination**: Do NOT change loop termination logic — patience_counter and max_iterations must remain unchanged
- **Bundled loop-control changes**: Defer top-k oscillation fix, monotonic improvement policy, dead-end granularity to separate experiments
- **Untested template changes**: Test each template variant with at least one package
- **Breaking sanitize_gha_expressions consumers**: Relocate BEFORE deleting builder.py

## Research Foundation

Three parallel researchers completed, all PROCEED:

1. **Local Research**: Complete code-level map of Builder removal — 11 files, 6 injection points, critical dependency identified (sanitize_gha_expressions)
2. **External Research**: Reproducible Java builds taxonomy (Sharma et al. 2025), flat-template-with-conditionals confirmed correct, divergence→spec_override mapping validated
3. **Context Research**: Builder never achieved L4 (0/8), net-zero oscillation, AnalyzeAgent validated in exp 10, L3→L4 frontier needs reproducibility parameters
