---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
  - cycle-summary
  - final
date: 2026-06-19
run_id: run-4b6edc0c
source: factory-archivist
---

# Factory Cycle Summary: buildroot-reconstructor — run-4b6edc0c (Final Archive)

## Overview

**Run ID**: run-4b6edc0c
**Duration**: 2026-06-07 to 2026-06-19 (13 days)
**Experiments**: 18 executed (IDs 1–10, 12–13, 15–18)
**Verdicts**: 15 KEEP, 1 REVERT (experiment #10)
**Keep Rate**: 93.8% (15/16 decided)
**Final Keep Streak**: 6 consecutive KEEPs (#012, #013, #015, #016, #017, #018)
**Score Trajectory**: 0.6433 (baseline) → 0.9282 (final) — net +0.2849
**Peak Score**: 0.9282 (experiment #018)
**Final Eval**: 0.606 composite (last_eval.json — hygiene-weighted, distinct from experiment scoring)
**Mode**: Evolved from explore-heavy (early) to targeted single-hypothesis (late)

## Score Arc

```
 0.95 ─                                                        ████ #018
 0.85 ─ ████ #001  ████ #003  ████ #004     ████ #007─#009
 0.80 ─                                  ████ #013
 0.75 ─
 0.70 ─
 0.65 ─ base                                                 ████ #017
 0.60 ─                        ████ #006     ████ #012  ████ #015─#016
 0.55 ─
 0.50 ─                                  ████ #012
 0.45 ─
 0.30 ─              ████ #003 (before)
       ├──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤
       Day 1    3      5      7      9     11     12     13
```

## Complete Experiment Timeline

| # | Date | Hypothesis | Verdict | Score Δ | Category |
|---|------|-----------|---------|---------|----------|
| 1 | 06-07 | Fix all 6 Level 3 gaps | KEEP | +0.2066 | FIX |
| 2 | 06-08 | Level 3 build verification refinement | KEEP | 3→10/10 builds | FIX |
| 3 | 06-08 | Level 4 multi-layer JAR comparison | KEEP | +0.5418 | EXPLORE |
| 4 | 06-09 | PNC ground-truth validation | KEEP | +0.2807 | EXPLORE |
| 5 | 06-12 | PNC validation on rh-h100-01 | KEEP | operational | EXPLORE |
| 6 | 06-12 | Agentic reconstructor inner loop MVP | KEEP | +0.0038 | EXPLORE |
| 7 | 06-13 | Outer loop with failure analysis | KEEP | +0.0427 | FIX |
| 8 | 06-13 | Claude Code agent migration | KEEP | +0.0014 | FIX |
| 9 | 06-15 | Node-scoped agents (13 reviewers) | KEEP | -0.001 (noise) | EXPLORE |
| 10 | 06-16 | Agent architecture overhaul | **REVERT** | -19.4pp L4 | EXPLORE |
| 12 | 06-17 | Elitist gate with patience counter | KEEP | +0.025 | FIX |
| 13 | 06-17 | 8 pipeline critique fixes | KEEP | +0.2900 | FIX |
| 15 | 06-18 | Remove Builder, 3-tier spec_overrides | KEEP | -0.0728 | EXPLORE |
| 16 | 06-18 | Wire up diagnostic feedback loop | KEEP | 0.0000 | FIX |
| 17 | 06-19 | Agent System v3 design issue | KEEP | 0.0000 | EXPLORE |
| 18 | 06-19 | Agent System v3 full implementation | KEEP | +0.3274 | EXPLORE |

## Five Phases of Evolution

### Phase 1: Foundation (Exps 1–4, Days 1–3)
Built the deterministic pipeline: Level 3 gap fixes, build verification, Level 4 JAR comparison, and PNC ground-truth validation. Score rose from 0.6433 to 0.8243. Established the 4-level scoring hierarchy (L1→L4) that remained the project's evaluation backbone throughout.

### Phase 2: Agentic Capabilities (Exps 5–9, Days 5–9)
Added the agentic layer: inner loop MVP, outer loop intelligence, Claude Code agent migration, and 13 node-scoped reviewer agents. Score plateaued at ~0.845 — the deterministic pipeline was already strong, and the agentic components were infrastructure rather than immediate value.

### Phase 3: The Revert and Recovery (Exps 10, 12–13, Days 9–11)
Experiment #10 — the agent architecture overhaul — regressed L4 rate from 22.6% to 3.2% due to aggressive early termination. First and only revert in the project. The elitist gate (#12, +0.025) and 8 critique fixes (#13, +0.290) recovered and surpassed the pre-revert score.

**Key lesson**: checkpoint-and-restore beats early termination for stochastic LLM-based optimizers. Experiment #10's failure informed every subsequent design decision.

### Phase 4: Architectural Cleanup (Exps 15–17, Days 12–13)
Removed the Builder agent (net-zero, 89% budget waste), wired up the diagnostic feedback loop (dead code activation), and produced the comprehensive Agent System v3 design document (issue #51, 12,000+ words, 113 requirements). Score dipped to 0.6321 due to capability_surface reduction — intentional.

### Phase 5: Agent System v3 (Exp 18, Day 13)
The culmination: full v3 implementation — 8 phases, +3066/-2833 lines, 40 files, 110 new tests. Single Analysis Agent replaces 11 node agents + AnalyzeAgent. Score jumped 0.6008 → 0.9282 (+0.3274) — the largest single-experiment gain in the project.

## Top 5 Experiments by Impact

1. **#003** (+0.5418) — Level 4 JAR comparison pipeline. Foundation of all future evaluation.
2. **#018** (+0.3274) — Agent System v3. Largest absolute gain; delivered the entire v3 architecture.
3. **#013** (+0.2900) — 8 pipeline critique fixes. Multiplicative effect from information flow improvements.
4. **#004** (+0.2807) — PNC ground-truth validation. External benchmark against real build infrastructure.
5. **#001** (+0.2066) — Level 3 gap fixes. First experiment, established the improvement pattern.

## What Was Built

### Pipeline Architecture (Final State)

```
CLI (--pipeline v3) → run_inner_loop()
  ├── Pre-Pass: run_prepass() → deterministic data gathering
  ├── Template: BUILDROOT_SCHEMA (20 fields) → Jinja2 → Containerfile
  ├── Analysis Agent: claude-opus-4-6, full tool access, 30 turns/900s
  │     ├── 6-step investigation strategy
  │     ├── Multi-variant output (1–3 candidates per iteration)
  │     └── Warm-start from existing Containerfile (reverse_parse)
  ├── Feedback: build_feedback_context()
  │     ├── Template-value diffs
  │     ├── Elitist gate (revert on regression)
  │     ├── Dead-end tracking (FailedApproach list)
  │     ├── Stagnation detection (2× same hash+reward)
  │     ├── Oscillation detection (A-B-A pattern)
  │     └── Double confirmation (2× builds ≥ 0.98)
  ├── Scorer: multi-signal fallback (bytecode 0.40 + manifest 0.30 + unit_tests 0.30)
  └── RecipeStore: cross-package transfer (get_group_hints())
```

### Test Suite
- 131 unit tests passing (110 new in exp #18 + existing)
- Type checking clean (mypy)
- Lint clean (ruff)

### Open PRs (8)
#54, #52, #47, #43, #37, #33, #26, #21, #15

### Merged PRs (2)
#18 (outer loop), #11 (PNC validation)

## Research Archive

- **50 source notes** in `.factory/archive/sources/` — spanning local codebase analysis, external research, and CEO verdicts
- **16 experiment notes** in `.factory/archive/experiments/` — every decided experiment documented
- **29 strategy snapshots** in `.factory/archive/strategies/` — full decision trail
- **27+ patterns** in `.factory/archive/patterns/patterns.md` — cross-project lessons

## Lessons from This Factory Run

1. **The Revert was the most valuable experiment.** Experiment #10 (-19.4pp) taught that early termination kills stochastic optimizers. Every subsequent experiment internalized this — the elitist gate (#12), stagnation detection (#13), and v3's feedback loop (#18) are all direct descendants.

2. **Deletion compounds.** Builder removal (#15, -595 lines) → AnalyzeAgent cleanup → v3 (#18, -2829 lines) — each deletion made the next architecture simpler. Net over 3 experiments: +3486/-3683 lines (net -197).

3. **Design-as-experiment works.** Experiment #17 (design doc, Δ0.0) created issue #51, which became the spec for #18 (+0.3274). The zero-delta design experiment was the precondition for the project's largest gain.

4. **Targeted > broad.** After the #10 revert, every experiment used a single targeted hypothesis. The 6-experiment keep streak (100%) validated this approach vs. the earlier multi-hypothesis style.

5. **Score trajectory is non-monotonic.** The path was: 0.64 → 0.85 → 0.85 (plateau) → crash to 0.03 L4 → recover to 0.79 → intentional dip to 0.63 → final jump to 0.93. Progress requires accepting temporary regressions for architectural improvement.

## Final State

- **Score**: 0.9282 (experiment scoring) / 0.606 (hygiene-weighted eval)
- **Architecture**: Pipeline v3 with single Analysis Agent, structured schema, multi-signal scoring
- **Code**: ~3000 lines core pipeline, 131 tests, 0 lint/type errors
- **Knowledge base**: 50 source notes, 16 experiment notes, 29 strategy snapshots, 27+ patterns
- **Next steps**: E2E benchmark on rh-h100-01 with v3 pipeline (3-package then 31-package), merge 8 open PRs
