---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 6
verdict: KEEP
score_delta: "+0.0038"
score_before: 0.5662
score_after: 0.5700
date: 2026-06-13
source: factory-archivist
---

# Experiment #006: Agentic Reconstructor Inner Loop MVP with Outer Loop Skeleton

## Hypothesis
Implement Phase 1 agentic reconstructor: an LLM-driven iterative Containerfile repair loop (inner loop) with batch processing scaffold (outer loop), targeting capability_surface jump from 0.306 to ~0.6 via 8 new modules and CLI command.

## Result
**KEEP** — Score 0.5662 → 0.5700 (+0.0038). CEO code review CLEAN (iteration 2). PR #15 open, +1703/-0 lines, 15 files, 2 commits. 75 unit tests all passing. 3 security fixes applied during review. Operationally validated on rh-h100-01 with 3 packages.

## What Changed

### New Modules (8 under `src/buildroot/agent/`)
| Module | Role | Description |
|--------|------|-------------|
| `models.py` | Data | Dataclasses for BuildAttempt, EvalResult, DeadEndEntry, AgentConfig |
| `observer.py` | Observer | LLM-driven Containerfile analysis, mutation proposal via Vertex AI |
| `builder.py` | Builder | SSH remote `podman build` execution with timeout handling |
| `evaluator.py` | Evaluator | 4-level evaluation: L1 parse, L2 podman build, L3 build command, L4 JAR comparison |
| `analyzer.py` | Analyzer | Regex error classification (18 categories), LLM fallback, dead-end registry, G_t signal |
| `loop.py` | Orchestrator | Inner loop: Observer→Builder→Evaluator→Analyzer cycle, max 15 iterations |
| `outer_loop.py` | Batch | Outer loop: batch processing from package list, per-package results, solve_rate |
| `__init__.py` | Package | Module docstring |

### CLI
- `buildroot agent <coordinate>` — single-package agentic repair
- Flags: `--host`, `--max-iterations`, `--model`, `--batch`
- Batch mode: reads from `packages_smoke.txt`, outputs per-package results

### Key Design Decisions
1. **AdaEvolve G_t progress signal** — exponential moving average (ρ=0.9) of eval score improvements for exploit/explore/meta-shift mode switching (τ_M=0.12, τ_S=0.02)
2. **Dead-end registry** — YAML-persisted, 2-failure threshold prevents revisiting exhausted approaches
3. **GHA expression sanitization** — `${{ }}` stripping as pre-flight before every build (addresses 7/10 exp #003 failures)
4. **4-level evaluation** — reuses existing modules (containerfile parser, podman build, jar_comparator)
5. **Vertex AI integration** — `AnthropicVertex(region="us-east5", project_id="itpc-gcp-ai-eng-claude")` with `claude-opus-4-6`

### Tests
- 75 unit tests across 4 files (`test_agent_models.py`, `test_agent_analyzer.py`, `test_agent_evaluator.py`, `test_agent_loop.py`)
- All 75 passing
- Tests cover: error classification, dead-end registry, G_t computation, mode switching, eval scoring, loop termination conditions

### Security Fixes (3)
1. **Heredoc injection** — unsanitized package coordinates in shell heredoc could inject commands; fixed with input validation
2. **Path injection** — user-controlled paths in outer loop could escape working directory; fixed with path canonicalization
3. **G_t cold-start spike** — initial G_t value of 0.0 caused immediate meta-shift on first iteration; fixed with warm-start at τ_M

### CEO Code Review
- **Iteration 1**: 1 issue found — `diff_summary` field missing from `EvalResult` dataclass
- **Iteration 2**: CLEAN — all 7 checklist items PASS (correctness, security, edge cases, tests, style, scope, guardrails)
- Fix commit: 5a3c5d9 (added `diff_summary` field, propagated to `BuildAttempt`)

## Operational Validation (rh-h100-01)

Agentic smoke test on 3 packages with max 15 iterations each, total elapsed 2395s:

| Package | Status | Best Reward | Iterations | Elapsed |
|---------|--------|-------------|------------|---------|
| commons-lang3:3.14.0 | **SOLVED** | 1.0 | 1 | 741s |
| micrometer-core:1.10.13 | budget_exhausted | 0.15 (L2 build) | 15 | 974s |
| spring-security-core:5.8.9 | budget_exhausted | 0.05 (L1 parse) | 15 | 681s |

- **Solve rate**: 1/3 (33.3%)
- **Key insight**: commons-lang3 solved in a single iteration — the pre-flight GHA sanitization + existing inference quality handles "easy" packages immediately
- **Failure analysis**: micrometer-core reached L2 (podman build succeeded) but couldn't pass L3 (build command); spring-security-core stuck at L1 (Containerfile parse errors)

## Research Grounding

This experiment is grounded in 10 archived sources spanning 5 research areas:
- **RepairAgent (ICSE 2025)**: LLM as autonomous repair agent, tool selection over fixed pipelines
- **AprMcts (2025)**: MCTS for program repair, UCT C=0.7, beta=0.8 forgetting factor
- **SWE-Search (ICLR 2025)**: 3-agent architecture validates Observer/Builder/Evaluator split
- **SGAgent**: Multi-agent repair with escalation, maps to G_t mode switching
- **CI-Repair-Bench**: 18.9% single-shot rate confirms iterative approach is essential
- **AdaEvolve**: G_t progress signal with mode switching (exploit/explore/meta-shift)

## Commits
1. `887ec55` — feat: agentic reconstructor inner loop MVP with outer loop skeleton
2. `5a3c5d9` — fix: add diff_summary field to EvalResult and propagate to BuildAttempt
3. `50593b1` — results: agentic reconstructor smoke test on 3 packages
4. Additional review fix commits: `388ef0e`, `9dd397c`, `ebb44d5`, `b7050f7`

## Links
- Project: buildroot-reconstructor
- Issue: #14
- PR: #15 (OPEN, +1703/-0, 15 files)
- Strategy: `strategies/buildroot-reconstructor-2026-06-13-agentic-inner-loop.md`
- Research: 10 source notes under `sources/` (repairagent, aprmcts, swe-search, sgagent, mini-swe-agent, codex-iterative, ci-repair-bench, dead-end-registries, maven-build-error-taxonomy, agentic-codebase-mapping)
- Smoke test results: `results/agent-smoke/summary.json`
