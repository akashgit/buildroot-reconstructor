---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
  - cycle-summary
  - final
date: 2026-06-13
source: factory-archivist
---

# Complete Factory Cycle Summary: buildroot-reconstructor — 2026-06-13

## Overview

Full factory cycle: 8 experiments, 8 kept, 0 reverted. The project evolved from a bare scaffold to a 4-layer autonomous build reconstruction system with Claude Code subprocess agents. Final eval score: **0.8456**.

Key milestone in experiment #008: migrated all LLM agents from raw `AnthropicVertex` API calls to Claude Code subprocess spawning (`claude -p`), giving agents tool access, multi-turn iteration, and structured output. Added a new Outer Researcher agent for web-based failure research.

## Experiment Log

| # | Hypothesis | Verdict | Score Delta | Tests Added | PR |
|---|-----------|---------|-------------|-------------|-----|
| 1 | Fix 6 Level 3 rebuild gaps | KEEP | +0.2066 | 35 | #3 |
| 2 | Level 3 build verification refinement | KEEP | n/a | — | — |
| 3 | Level 4 multi-layer JAR comparison | KEEP | +0.5418* | 26 | #7 |
| 4 | PNC ground-truth validation | KEEP | +0.2807* | 41 | #11 (merged) |
| 5 | PNC execution on rh-h100-01 | KEEP | n/a | — | — |
| 6 | Agentic inner loop MVP | KEEP | +0.0038 | 75 | #15 |
| 7 | Intelligent outer loop | KEEP | +0.0427 | 143 | #18 (merged) |
| 8 | Claude Code agent migration | KEEP | +0.0014 | 29 | #21 |

*Score deltas for #003/#004 reflect eval rubric changes; not directly comparable across rubric boundaries.

## Aggregate Stats

| Metric | Value |
|--------|-------|
| Experiments | 8/8 kept (perfect streak) |
| Final eval score | 0.8456 |
| Baseline score | 0.6433 |
| Net score gain | +0.2023 |
| Total tests | 430 passing |
| Core features | 13 (all delivered) |
| PRs merged | #11, #18 |
| PRs open | #3, #7, #15, #21 |
| Agentic solve rate | 1/3 (33.3%) |
| PNC validation accuracy | 0.5833 mean |
| Lines of code added | ~7500+ across all experiments |

## What Was Built — 4-Layer Architecture

### Layer 1: Static Inference Pipeline (experiments #001–#003)
POM parsing with full parent resolution, Maven property resolution, CI workflow parsing (GitHub Actions + CircleCI), 12-source JDK inference heuristic, container image resolution, transitive dependency tree, Containerfile generation (3 Jinja2 templates), gap detection, multi-layer JAR comparison (structural/metadata/bytecode with CFR decompiler).

### Layer 2: External Validation (experiments #004–#005)
PNC ground-truth Containerfile parser, 6-dimension weighted accuracy scorer (JDK version 0.25, build tool 0.25, tool version 0.15, SCM 0.15, JDK vendor 0.10, OS family 0.10), validated on 3 real packages against PNC build system (mean accuracy 0.5833).

### Layer 3: Agentic Inner Loop (experiment #006)
LLM-driven iterative Containerfile repair: Observer→Builder→Evaluator→Analyzer cycle with AdaEvolve G_t mode switching (exploit/explore/meta-shift), dead-end registry (2-failure threshold), 18-category error classification with LLM fallback, 4-level reward evaluation, GHA expression sanitization.

### Layer 4: Intelligent Outer Loop + Claude Code Agents (experiments #007–#008)
Failure analyst (batch analysis, error class frequency, stagnation detection), cross-package knowledge base with inner loop injection, 4-guard safety chain (surface/leakage/monotonic/test), J(S) strategy scoring (AdaEvolve formula), LLM outer strategist, Outer Researcher (web research on failure patterns). All agents migrated to Claude Code subprocess spawning via shared `claude_runner.py` with per-agent tool restrictions.

## Agent Architecture (post experiment #008)

| Agent | Tool Surface | Mode |
|-------|-------------|------|
| Inner Builder | Read, Edit, Bash | Iterative (10 turns, $5 budget, 600s timeout) |
| Outer Builder | Read, Edit, Bash | Surgical file edits via Edit tool |
| Outer Strategist | Read, Bash | Structured output via --json-schema |
| Outer Researcher | Read, WebSearch | Web research on failure patterns |

All agents use `spawn_claude_agent()` from `claude_runner.py` with `--bare --append-system-prompt-file --dangerously-skip-permissions`.

## Score Trajectory

| Experiment | Score | Delta |
|------------|-------|-------|
| Baseline | 0.6433 | — |
| #001 (L3 gaps) | 0.8499 | +0.2066 |
| #002 (L3 builds) | — | operational |
| #003 (L4 JAR compare) | 0.8500 | +0.5418* |
| #004 (PNC validation) | 0.8243 | +0.2807* |
| #005 (PNC execution) | — | operational |
| #006 (Inner loop) | 0.5700 | +0.0038 |
| #007 (Outer loop) | 0.8439 | +0.0427 |
| #008 (Claude Code migration) | 0.8456 | +0.0014 |

## Key Patterns Discovered (17 total in patterns.md)

Most impactful:
1. **Pre-flight sanitization beats iterative repair** for known error classes (GHA expressions: regex strip ~100% vs 18.9% LLM repair rate)
2. **Infrastructure migrations show small eval deltas** — use capability unlock as the KEEP signal, not score
3. **Guard-chain safety model works** — 8/8 keep streak with 4-guard chain + CEO code review + per-agent tool restrictions
4. **Easy packages solve instantly, hard packages exhaust budget** — bimodal distribution, early termination needed
5. **Knowledge base injection should be additive** — prepend meta_guidance, don't replace system prompt
6. **Parallel research with complementary scopes eliminates overlap** — scope by information source (local/external/context)

## Research Corpus

40+ source notes archived in `.factory/archive/sources/`, covering:
- Prior art landscape (Macaron, OSS-Rebuild, Reproducible Central, AROMA)
- Implementation research (POM parsing, Jinja2 templates, JDK inference, Maven dependencies)
- Agentic repair literature (RepairAgent, AprMcts, SWE-Search, SGAgent, AlphaEvolve, CI-Repair-Bench)
- Outer loop design (AdaEvolve, AutoScientists, EvoX, Meta-Harness, LLMLOOP)
- Claude Code CLI migration (local analysis, external reference, context mapping)

## Open Items for Future Work

1. **Improve solve rate** beyond 33.3% — target micrometer-core and spring-security-core
2. **Merge open PRs**: #3 (L3 gaps), #7 (L4 JAR compare), #15 (inner loop), #21 (Claude Code migration)
3. **Early termination + budget reallocation** for bimodal package difficulty
4. **PNC-specific JDK resolution** — parse image name `builder-rhel-7-j{JDK}` as authoritative source
5. **OS family extraction** — underspecified in both reconstruction and ground truth
6. **Expand test package set** beyond 10 Spring ecosystem packages
7. **Exploit Claude Code tool access** — agents can now iterate with Read/Edit/Bash, enabling more sophisticated repair strategies
