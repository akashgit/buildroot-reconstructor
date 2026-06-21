---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-13
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-13 (Outer Loop)

## Context
- **Cycle**: 7
- **Trigger**: Inner loop feature-complete (6/6 experiments kept), solve rate 33.3% — outer loop is the next major capability
- **Current Score**: 0.5700
- **CEO Verdict**: PROCEED — plan approved as single hypothesis in targeted mode

## Strategy Decision

### H1: Implement Outer Loop with Failure Analyst, Knowledge Base, Guards, and Strategy Archive
- **Category**: EXPLORE
- **Type**: mixed (code + E2E execution)
- **Backlog Item**: Issue #16 — Outer Loop: Cross-Package Improvement with Failure Analysis and Knowledge Base
- **Growth Dimension**: capability_surface

### Phased Implementation Order (CEO-approved)

**Phase 1 — Failure Analyst + Knowledge Base (foundation)**
- `failure_analyst.py`: Aggregates error classes from `LoopResult`, classifies exhausted vs under-explored, implements AutoScientists stagnation trigger (>=8 failures in <=3 classes)
- `knowledge/` directory: `patterns.md` (learned heuristics by package type), `failure_taxonomy.md` (error class table), `package_clusters.md` (build characteristic groups)
- `knowledge_base.py`: Reader/writer with `read_patterns()`, `update_taxonomy()`, `record_pattern()`
- Inner loop injection: `meta_guidance` parameter on `Builder.__init__()` — outer loop injects relevant patterns into system prompt

**Phase 2 — Guards & Gates (real enforcement)**
- `guards.py`: Four functions returning `GuardResult(passed, reason)`
  - `check_surfaces()`: Allowlist enforcement — reject changes to evaluator.py, jar_comparator.py, packages_smoke.txt
  - `run_test_gate()`: Execute pytest + ruff, return pass/fail
  - `check_monotonic()`: Reject if solve_rate regresses
  - `scan_leakage()`: Grep diff for hardcoded coordinates, version strings, package-specific conditionals

**Phase 3 — Outer Strategist + J(S)**
- `outer_strategist.py`: Takes `FailureAnalysis` + knowledge base, generates `CodeChangeHypothesis`
- J(S) = (s_end - s_start) * log(1 + s_start) / sqrt(W) for strategy scoring
- Stagnation detection: J < 0.01 for 3 consecutive cycles triggers architectural shift
- Skip Outer Researcher for v1 — CEO and research agree LLM knowledge + archive sufficient

**Phase 4 — Orchestrator + Code Mutation Builder**
- Rewrite `outer_loop.py`: `run_batch()` -> `FailureAnalyst.analyze()` -> `OuterStrategist.propose()` -> `OuterBuilder.implement()` -> `git apply` -> `guards.check_all()` -> `run_batch()` -> verdict -> `knowledge_base.update()` -> loop
- `OuterBuilder`: LLM call producing modified file content (full-file rewrite for <200 lines)
- Strategy archive: per-cycle YAML files recording hypothesis, files_changed, solve_rate delta, verdict, j_score

**Phase 5 — CLI + Hygiene fixes**
- `--outer-loop`, `--target-solve-rate`, `--max-cycles` flags on `agent_cmd.py`
- Fix existing type errors: builder.py:96, evaluator.py:209/215, outer_loop.py:74
- Fix ruff errors: unused pytest imports in test files
- Comprehensive tests: ~50 tests across 5 new test modules

### Expected Impact
| Dimension | Before | After | Notes |
|-----------|--------|-------|-------|
| tests | 0.0 | 0.8+ | Fix module install + ~50 new tests |
| lint | 0.0 | 0.9+ | Fix 7 ruff errors |
| type_check | 0.0 | 0.8+ | Fix 14 mypy errors |
| coverage | 0.0 | 0.6+ | New test modules |
| observability | 0.12 | 0.3 | Logging in new modules |
| capability_surface | — | significant | 8 new components |
| **Composite** | **0.0** | **0.65+** | Above 0.6 threshold |

### Anti-patterns (CEO-mandated)
1. No stubbed guards — all must execute real subprocess calls
2. No package-specific answers embedded in code changes
3. No full-codebase context dumps to Builder LLM — memory pointer pattern only
4. No Outer Researcher in v1
5. No modifications to evaluator.py or jar_comparator.py (fixed surfaces)
6. No UCB1 bandit scheduling or parallel batch runs
7. No cold-start J(S) — warm-start with first cycle's solve_rate

### Research Grounding
- AdaEvolve J(S) formula validated across 185 problems
- AutoScientists stagnation triggers at >=8 failures in <=3 classes
- EvoX strategy-as-code with demand-driven switching
- Meta-Harness confirms harness optimization is tractable
- LLMLOOP per-error-type feedback loops

### CEO Notes for Builder
- Timeout: 1800s (mixed hypothesis with operational component)
- E2E requirement: Builder must implement real guards, orchestrator must be runnable end-to-end
- Key integration test: `meta_guidance` injection into inner loop Builder
- If Outer Researcher omitted, mark backlog item as PARTIAL

## Design Space Snapshot
| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | Inner loop complete, L1-L4 verification, PNC validation, JAR comparison |
| Bug fixes | 3 | Multiple security fixes addressed |
| Instrumentation | 1 | 15% function coverage, sparse structured logging |
| Flow changes | 2 | Inner loop AdaEvolve works; outer loop is dumb for-loop |
| New agents | 2 | Observer, Builder, Evaluator, Analyzer exist; no Failure Analyst, Researcher, Strategist |
| Prompt engineering | 2 | Builder has 3 mode prompts; no knowledge injection |
| Eval improvements | 1 | eval/score.py exists but hygiene dimensions at 0.0 |
| Knowledge management | 0 | No knowledge base, no strategy archive, no cross-package learning |
| Infrastructure | 3 | SSH remote execution, podman builds, CLI entry points |
| Self-evolution | 0 | No outer loop code mutation, no guards/gates, no J(S) tracking |

**Underserved**: Knowledge management (0), Self-evolution (0), Instrumentation (1)
