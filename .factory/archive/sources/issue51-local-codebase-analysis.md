---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-19
---

# Issue #51 Local Research: Codebase Structure & Gap Analysis

## Critical Finding: pipeline_v2.py Does Not Exist

Issue #51 repeatedly references `pipeline_v2.py` as the foundation for v3 ("v3 is built directly on pipeline_v2.py"). However, **this file does not exist** in the current codebase. The implementation must create a new `pipeline_v3.py` file, drawing from the current `loop.py` architecture. The core loop in `loop.py` already has many of the patterns v3 needs (elitist gate, warm-start, recipe store, Top-K evaluation).

## Codebase Inventory (Agent Module)

| File | Lines | v3 Disposition |
|------|-------|----------------|
| `models.py` | 250 | **Modify** — add `FailedApproach`, extend `RecipeStore` with `get_group_hints()` |
| `loop.py` | 570 | **Modify** — add `pipeline` param, stagnation/oscillation/double-confirm (P3), fallback termination (P4) |
| `evaluator.py` | 290 | **Modify** — fix diff_summary bug (A1, P2), add `_l4_fallback_signals()` (P4) |
| `observer.py` | 73 | **Keep** — basis for `run_prepass()` (P1) |
| `augmented_observer.py` | 225 | **Remove** in P8 (replaced by Analysis Agent) |
| `analyzer.py` | 902 | **Modify** — `AnalyzeAgent` class replaced in P2; keep error classification until P8 |
| `claude_runner.py` | 177 | **Keep** unchanged |
| `node_agents/*.py` | 11 files | **Remove** in P8 |

## Confirmed Bugs

### Bug A1: diff_summary Dead Code (evaluator.py:162-175)
All 6 attribute references use wrong names. Correct paths from `jar_comparator.py`:
- `report.structural.diff.missing` (not `.details.missing_files`)
- `report.structural.diff.extra` (not `.details.extra_files`)
- `report.metadata.manifest_diff_keys` (not `.details.differing_keys`)
- `report.bytecode.classes_divergent` (not `.details.divergent_classes`)

### Bug A2: No-JAR Dead Loop
When no JAR on Maven Central, `_download_original_jar()` returns None, sets error_summary but `classify_error()` returns "unknown" (not in FUNDAMENTAL_BLOCKERS), loops 15 times doing nothing.

## Gap Analysis Summary

| Phase | Requirements | Already Implemented | Missing |
|-------|-------------|--------------------|---------| 
| P1: Data Models + Pre-Pass | 16 | 2 partial | 14 |
| P2: Analysis Agent + Evaluator Fix | 8 | 0 | 8 |
| P3: Feedback Loop + Loop Control | 18 | 3 partial | 15 |
| P4: Multi-Signal Fallback Scoring | 12 | 0 | 12 |
| P5: CLI Integration | 2 | 0 | 2 |
| P6: Optimizations | 5 | 1 partial | 4 |
| P7-P8: Benchmark + Cleanup | 8 | 0 | 8 deferred |

## Existing Code That Maps to v3

Key reuse opportunities:
- Elitist gate (G7): `loop.py:157-168` patience_counter — adapt for template values
- Dead-end tracking: `models.py:DeadEndEntry` — extend with `FailedApproach`
- Recipe store + warm-start: `models.py:RecipeStore` + `loop.py:290-349`
- Error classification: `analyzer.py:ERROR_PATTERNS` (21 patterns) — keep until P8
- Error loop detection: `analyzer.py:detect_error_loop()` — adapt for template value oscillation
- SSH build infrastructure: `evaluator.py:Evaluator` — keep unchanged

## Quantitative Summary

- Total requirements in issue #51: 113
- Remaining to implement (P1-P6): 67
- New files to create: 8 (4 source + 4 test)
- Existing files to modify: 5
- Confirmed bugs: 2
- Current test count: 440
- Estimated new tests: ~60
