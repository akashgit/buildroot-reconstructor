---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-19
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-19 (Agent System v3 Implementation)

## CEO Verdict: PROCEED — PLAN APPROVED

### Context
- **Issue**: #51 — Agent System v3: all 8 phases, 113 requirements, 3-package benchmark scoring .9+
- **Current Score**: 0.632
- **Weakest Dimension**: capability_surface (0.380)
- **Mode**: Targeted — single hypothesis covering full v3 scope
- **Prior Cycle**: Issue #48 (design doc) — COMPLETE, KEEP, deliverable is issue #51 + PR #52
- **Keep Streak**: 5 consecutive (#012, #013, #015, #016, #017)

### Approved Hypothesis

**H1: Implement Agent System v3 — Full Scope (Issue #51, All 8 Phases, 113 Requirements)**
- **Category**: EXPLORE
- **Priority**: HIGH
- **Growth Dimension**: capability_surface (0.380 → 0.80+ target)
- **Expected Impact**: 3-package benchmark from (0.15, 0.50, 0.50) to (0.90+, 0.90+, 0.90+); 31-package solve rate 29% → 50%+

### 8 Implementation Phases

**Phase 1 (P1): Data Models + Pre-Pass** (16 requirements: E1-E9, I1-I5, D9, D12, D13, D16)
- Create `src/buildroot/agent/prepass.py`: PrePassFinding, PrePassFindings dataclasses, run_prepass(), to_prompt()
- Add FailedApproach to models.py, extend BuildrootSpec with 5 new fields
- Create `tests/test_prepass.py` (~15 unit tests)

**Phase 2 (P2): Analysis Agent + Evaluator Bug Fix + Pipeline v3 Core** (8 requirements: A1, D1, D3, D5, D6, D7, D13, J2)
- Fix evaluator diff_summary dead code (evaluator.py:162-175, 6 wrong attribute names)
- Create `src/buildroot/agent/pipeline_v3.py` (~500-700 lines): BUILDROOT_SCHEMA, Analysis Agent config (claude-opus-4-6, full tools), enhanced system prompt
- Create `tests/test_evaluator_diff_summary.py` (~10 unit tests)

**Phase 3 (P3): Feedback Loop + Loop Control** (18 requirements: G1-G11, G13, H5, H6, H8, D10, D17, A4)
- Create `src/buildroot/agent/feedback.py`: build_feedback_context(), template-value diffs, hash functions
- Integrate elitist gate (from loop.py:157-168), dead-end tracking, stagnation/oscillation detection, double confirmation
- Create `tests/test_feedback.py` (~20 unit tests)

**Phase 4 (P4): Multi-Signal Fallback Scoring** (12 requirements: F1-F7, A2, H3, H4, J4)
- Create `src/buildroot/agent/scorer.py`: ScoreBreakdown, fallback scoring (bytecode 0.40 + manifest 0.30 + unit_tests 0.30)
- l3_ceiling and fallback_ceiling_reached termination conditions
- Create `tests/test_scorer.py` (~15 unit tests)

**Phase 5 (P5): CLI Integration + Pipeline Wiring** (2 requirements: J3, B10)
- Add `--pipeline v3` to CLI, `pipeline` param to run_inner_loop() and outer_loop.py
- Create `results/packages_fast_iteration.txt` (3 benchmark packages)

**Phase 6 (P6): Optimizations** (5 requirements: D8, D15, G12, G14, H9)
- Cross-package knowledge transfer via RecipeStore
- Warm-start reverse-parse, parallel first build, multi-variant elitist, sub-agent strategy

**Phase 7 (P7): Benchmark + Default Switch** (1 requirement: J5)
- Full 31-package benchmark on rh-h100-01 with v3
- Success: v3 >= v1 (29% solve rate), no regressions → switch default

**Phase 8 (P8): Cleanup Deprecated Components** (5 requirements: C3, C4, C6, C8, J6)
- Remove augmented_observer.py, gap_detector.py, 11 node agent files, AnalyzeAgent class, ProgressSignal
- Verify all tests pass, no dead code references

### Execution Step
Run 3-package benchmark on rh-h100-01 after P1-P6:
```bash
ssh lab@rh-h100-01 "cd ~/buildroot-reconstructor && git pull"
ssh lab@rh-h100-01 "cd ~/buildroot-reconstructor && buildroot agent --batch results/packages_fast_iteration.txt --pipeline v3 --host localhost --max-iterations 10 --output results/fast-iteration-v3/"
```
Iterate until all 3 packages achieve reward >= 0.9 (L4 with l4_score >= 0.80).

### Benchmark Packages
| Package | Current | Target | Failure Class |
|---------|---------|--------|---------------|
| json-path:2.9.0 | L2 (0.15) | L4 (0.90+) | Wrong build system (Gradle) |
| junit:4.13.2 | L3 (0.50) | L4 (0.90+) | Plugin errors, multi-level progression |
| commons-fileupload:1.5 | L3 (0.50) | L4 (0.90+) | L3 stagnation (14 iterations in v1) |

### Critical Decisions
- **Create pipeline_v3.py from scratch** — pipeline_v2.py does NOT exist in codebase (never merged)
- **Draw from loop.py patterns**: elitist gate (lines 157-168), warm-start (lines 290-349), recipe store, Top-K evaluation
- **Enable full tool access for Analysis Agent**: ["Bash", "Read", "WebSearch", "WebFetch", "Agent"] — reverses current AnalyzeAgent's all-tools-blocked state
- **Phase-sequential implementation**: P1→P2→P3→P4→P5→P6→P7→P8, unit tests per phase
- **E2E mandatory after pipeline changes** — SSH as `lab` to rh-h100-01

### Anti-Patterns to Avoid (from prior experiments)
- Raw information dumps (exp #10, -19.4pp) — use structured summaries + file paths
- spec_overrides accumulation (Bug A3) — agent outputs COMPLETE template values
- Aggressive early termination (exp #10) — use stagnation detection, not iteration count
- Blocking agent tools (current AnalyzeAgent blocks ALL) — v3 enables full access
- Implementing without E2E validation — mandatory per project feedback

### Validated Design Patterns
- Structured feedback > raw dumps (exp #10 anti-pattern, -19.4pp)
- Elitist gate prevents regression (exp #12, +0.025)
- Complete template values > spec_overrides (exp #15, KEEP)
- Targeted improvements > broad rewrites (exp #13, +0.290)

### CEO Notes for Builder
- Create pipeline_v3.py (NOT pipeline_v2.py)
- Expect 2000+ lines of new code across ~9 new files
- Implement phases sequentially with unit tests after each
- After P5, create packages_fast_iteration.txt
- SSH to rh-h100-01 as `lab` (NOT akasriva) for E2E
