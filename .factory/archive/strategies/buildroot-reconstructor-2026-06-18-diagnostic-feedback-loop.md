---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-18
source: factory-archivist
experiment: pending (next experiment after strategy approval)
issue: 45
run_id: run-f1d753fa
---

# Strategy: buildroot-reconstructor — 2026-06-18 — Diagnostic Feedback Loop

## CEO Verdict

**PLAN APPROVED** — exactly ONE hypothesis (H1) approved for implementation.

## Context

- **Issue**: #45 — Wire up diagnostic feedback loop
- **Current Score**: 0.6029 (strategist observation) / 0.6086 (post-exp-15 dashboard)
- **Weakest Dimension**: capability_surface (0.3812)
- **Keep Streak**: 3 consecutive keeps (#012, #013, #015)
- **Overall Keep Rate**: 92.3% (12/13 decided)
- **Key Problem**: `build_remediation_context()` at analyzer.py:430-488 is fully implemented but has zero call sites — dead code with proven value. commons-lang3 regressed from L4 (reward=1.0) to L1 because the AnalyzeAgent receives truncated error summaries instead of structured diagnostics.

## Approved Hypothesis

### H1: Wire up diagnostic feedback loop — error history, remediation context, and node agent error awareness

- **Category**: FIX
- **Type**: code
- **Scope**: ~120 lines across 6 files
- **Priority**: high

### Implementation Steps (CEO-approved order)

1. **`loop.py` — Track error history and build progress.** Add `error_history: list[str]` and `previous_progress: analyzer.BuildProgress | None` before the iteration loop in both `_run_standard_loop` and `_run_agent_loop`. Append `analysis.error_class` to `error_history` and update `previous_progress` after each analysis.

2. **`loop.py` — Call `build_remediation_context()` and pass to AnalyzeAgent.** After `analyzer.analyze()` returns in both loops, call `remediation_context = analyzer.build_remediation_context(analysis, eval_result.build_log, error_history=error_history, previous_progress=previous_progress)`. Pass as new `remediation_context` kwarg to `analyze_agent.analyze_cycle()`.

3. **`analyzer.py:696` — Accept and inject remediation context in `analyze_cycle()`.** Add `remediation_context: str = ""` parameter. When non-empty, insert `## Structured Diagnostics\n{remediation_context}` section into the task prompt between build results and dead-end registry.

4. **`augmented_observer.py:82` — Accept and pass build error context in `observe_top_k()`.** Add `build_error_context: str = ""` parameter. Pass through to `agent.review()` via context dict.

5. **`loop.py` — Pass error context to `observe_top_k()` on re-observation.** When calling `observer.observe_top_k()` after a failed build, pass `build_error_context=f"Prior build failed at L{eval_result.level_reached}: [{analysis.error_class}] {analysis.fix_suggestion[:200]}"`.

6. **`node_agents/base.py` — Include build error in node agent task prompts.** When `context.get("build_error_context")` is non-empty, append `## Build Failure Context` section to the task prompt.

### Expected Impact

- **factory_effectiveness**: 0.54 → 0.60 (better diagnosis → fewer wasted iterations → higher keep rate)
- **experiment_diversity**: 0.49 → 0.54 (enables exploit-category experiments on improved feedback loop)
- **Indirect**: commons-lang3 regression becomes diagnosable — AnalyzeAgent will see "outputTimestamp outside valid ZIP date range" in structured diagnostics

## CEO Review Notes

- H1 excludes spec changes #3 (SOURCE_DATE_EPOCH template ordering), #5 (TemplateAgent fix vocabulary), and #6 (timestamp error pattern) — reasonable scoping, these are follow-up items
- Strategist uses string format for `build_error_context` instead of dict — valid simplification
- All changes within declared mutable_surfaces (loop.py, analyzer.py, augmented_observer.py, base.py)
- No fixed surfaces touched (evaluator.py, scoring pipeline untouched)

## Anti-Patterns Flagged

1. **Don't pass raw build logs to AnalyzeAgent** — exp #10 revert showed unstructured dumps degrade agent reasoning
2. **Don't enable tools for AnalyzeAgent** — `disallowed_tools` list at analyzer.py:732 is intentional
3. **Don't modify evaluator.py or scoring pipeline** — read-only surfaces
4. **Don't change SOURCE_DATE_EPOCH values** — separate concern from feedback loop wiring
5. **Don't duplicate error context** — `remediation_context` string is the single source of structured diagnostics

## Precedent

- Prior exp #013 showed +0.2900 from information flow improvements (same category of change)
- Elitist gate (#012) and spec_overrides (#015) are architectural prerequisites already in place
- Experiment #010 (REVERTED, -19.4pp L4) validated that unstructured information dumps cause regressions
