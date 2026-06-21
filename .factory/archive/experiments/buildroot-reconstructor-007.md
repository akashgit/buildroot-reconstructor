---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 7
verdict: KEEP
score_delta: +0.0427
score_before: 0.8012
score_after: 0.8439
date: 2026-06-13
source: factory-archivist
---

# Experiment #007: Intelligent Outer Loop with Failure Analyst, Guards, and Strategy Archive

## Hypothesis
Implement the outer loop intelligence layer: failure analysis across batch results, cross-package knowledge base with inner loop injection, safety guards (surface/leakage/monotonic/test gates), J(S) strategy scoring, and an LLM-driven outer strategist — enabling the system to autonomously improve its own solve rate across cycles.

## Result
**KEEP** — Score improved from 0.8012 to 0.8439 (+0.0427). Outer loop E2E verified on 3 real packages (1/3 solved). Full cycle working: batch→analyze→strategize→implement→guard→re-batch→verdict. Knowledge base injection, failure analysis, surface guards, J-score strategy all functional. PR #18 merged, +2258/-13 lines, 20 files, 143 new tests (399 total). CEO review found 2 issues (scope + correctness), Builder fixed in a362769.

## What Changed

### New Modules (5 under `src/buildroot/agent/`)
| Module | Role | Lines | Description |
|--------|------|-------|-------------|
| `failure_analyst.py` | Analyst | 187 | Aggregates batch failures, classifies error classes by frequency, detects exhausted vs under-explored approaches, AutoScientists stagnation trigger (≥8 failures in ≤3 classes) |
| `guards.py` | Safety | 252 | Four guard functions returning `GuardResult(passed, reason)`: `check_surfaces()` allowlist enforcement, `run_test_gate()` pytest+ruff gate, `check_monotonic()` regression rejection, `scan_leakage()` ground-truth leakage detection |
| `outer_strategist.py` | Strategist | ~180 | LLM-driven hypothesis generation from failure analysis, J(S) formula implementation `J = (s_end - s_start) · log(1 + s_start) / √W`, strategy archive with historical tracking |
| `knowledge/knowledge_base.py` | Knowledge | 132 | Cross-package learning: `read_patterns()`, `read_taxonomy()`, `record_pattern()`, `update_taxonomy()` — reads/writes markdown knowledge files |
| `knowledge/` package | Data | 3 files | `patterns.md` (learned heuristics), `failure_taxonomy.md` (7-class error table), `package_clusters.md` (build characteristic groups) |

### Modified Modules (3)
| Module | Change | Description |
|--------|--------|-------------|
| `builder.py` | +15 lines | Added `meta_guidance` parameter to `__init__()` and injection into system prompt via `_call_llm()` — enables outer loop to inject knowledge base patterns |
| `outer_loop.py` | Rewritten | Full outer loop orchestrator: failure analysis → strategy generation → builder execution → guard checks → keep/revert decision cycle |
| `agent_cmd.py` | Extended | Added `--cycles` flag for outer loop iteration control |

### New Test Files (7)
| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_failure_analyst.py` | 13 | Empty batch, mixed results, dominant error class, frequency sorting, exhausted/under-explored classification, stagnation trigger, save/load, serialization |
| `test_guards.py` | 20+ | Surface checking (mutable/fixed/glob/out-of-scope), monotonic regression, leakage scanning (coordinate embedding, version hardcoding, package conditionals), `check_all` composite |
| `test_outer_strategist.py` | 15+ | J(S) computation, strategy archive CRUD, hypothesis generation, stagnation handling |
| `test_knowledge_base.py` | 15+ | Pattern read/write, taxonomy updates, section extraction, empty file handling |
| `test_outer_loop_v2.py` | 20+ | Full cycle orchestration, keep/revert decisions, guard integration, multi-cycle progression |
| `test_agent_evaluator.py` | Extended | Additional edge cases |
| `test_agent_models.py` | Extended | Additional serialization tests |

### Key Design Decisions
1. **AdaEvolve J(S) formula** — `J = (s_end - s_start) · log(1 + s_start) / √W` for principled strategy scoring across cycles, normalizing for difficulty and work invested
2. **Four-guard safety chain** — surface allowlist, leakage scan, monotonic check, test gate — all must pass before a cycle's changes are kept
3. **Knowledge base injection** — outer loop reads `patterns.md` and prepends relevant patterns to the Builder's system prompt via `meta_guidance` parameter
4. **Strategy archive** — YAML-persisted history of hypotheses, J(S) scores, and verdicts for cross-cycle learning
5. **Stagnation detection** — AutoScientists-inspired trigger: ≥8 failures concentrated in ≤3 error classes signals need for meta-shift
6. **Leakage scanning** — regex-based detection of hardcoded Maven coordinates, version strings, and package-specific conditionals in diffs

### CEO Code Review Summary
- **Verdict**: ISSUES_FOUND (2 issues)
- **Issue 1 (scope)**: Root-level `packages_smoke.txt` duplicate — should only exist at `results/packages_smoke.txt`
- **Issue 2 (correctness)**: `guards.py:39` FIXED_SURFACES referenced `"packages_smoke.txt"` instead of `"results/packages_smoke.txt"`
- **Fix commit**: a362769 — removed duplicate file, updated FIXED_SURFACES path
- **Checklist**: Correctness PASS, Security PASS, Edge cases PASS, Missing tests PASS (143 new, 399 total), Style PASS, Scope PARTIAL, Guardrail PASS
- **Notes**: All 10 remaining mypy errors are pre-existing in files outside Builder's scope. Ruff clean (7→0 errors). meta_guidance injection properly threaded through `run_inner_loop() → Builder.__init__() → Builder._call_llm()`.

## Architecture

```
Outer Loop Cycle:
  1. Run batch (inner loop on all packages)
  2. Failure Analyst: aggregate errors, classify, detect stagnation
  3. Knowledge Base: read patterns, inject into Builder
  4. Outer Strategist: generate hypothesis from failure analysis + history
  5. Builder: apply LLM-generated code changes
  6. Re-run batch with changes
  7. Guards: surface check → leakage scan → monotonic check → test gate
  8. Verdict: keep (commit) or revert (rollback)
  9. Strategy Archive: record J(S) score and outcome
```

## Links
- Project: buildroot-reconstructor
- Issue: #16
- PR: #18
- Strategy: `strategies/buildroot-reconstructor-2026-06-13-outer-loop.md`
- Research: `sources/adaevolve-outer-loop-hierarchy.md`, `sources/autoscientists-self-organizing-teams.md`, `sources/evox-meta-evolution-strategy.md`
- Prior experiment: #006 (inner loop MVP)
