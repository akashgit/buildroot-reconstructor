---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-48
source: factory-archivist
date: 2026-06-19
---

# Issue #48 Context Research — Complete Requirements Synthesis

## Sources Analyzed

| Source | Description |
|--------|-------------|
| Issue #48 body | Simplified pipeline: Analysis Agent + multi-signal scoring (64 requirements) |
| Comment 1 (akashgit) | Observer pre-pass proposal (9 requirements) |
| Comment 2 (akashgit) | 10 accuracy gaps critique (19 requirements) |
| Comment 3 (akashgit) | 10 speed/accuracy critiques (13 requirements) |
| Issues #42, #27, #24 | Prior design issues |
| Experiments #9–16 | Empirical constraints |

**Total: 113 distinct requirements across 10 categories (A–J)**

## Critical Experiment Constraint

**Exp #10 anti-pattern: raw unstructured dumps cause -19.4pp regression.** This is the single most important design constraint. ALL feedback to the agent MUST be structured. Write full artifacts to files; provide structured summary in prompt; agent uses Read tool for deep investigation.

## Requirement Categories

- **A: Bugs to Fix** (5) — dead code in diff_summary, no-JAR dead loop, spec_overrides accumulation, empty remediation at L4, tool starvation
- **B: Architecture — Keep** (10) — templates, JAR comparator, evaluator, recipe store, Maven/GitHub utils, Claude runner, reward formula, BuildrootSpec, CLI
- **C: Architecture — Remove** (11) — Observer→pre-pass, AgentAugmentedObserver, GapDetector, 11 NodeAgents, AnalyzeAgent, classify_error, remediation context, spec_overrides pattern, ProgressSignal, Builder
- **D: Analysis Agent Design** (17) — full tool access, opus model, budget caps (30/15 turns), system prompt with investigation strategy, evidence hierarchy, sub-agent strategy, complete template values per iteration
- **E: Deterministic Pre-Pass** (9) — PrePassFindings dataclass, attempted_but_failed, pom_data, ci_data, data-gathering only
- **F: Multi-Signal Scoring** (7) — fallback signals (bytecode_version_match, manifest_sanity, unit_tests_pass), graceful degradation
- **G: Feedback Loop Design** (14) — full build log as file, score history, elitist gate, dead-end tracking, rendered Containerfile, template-value diffs, cross-package knowledge, warm-start
- **H: Termination & Loop Control** (9) — stagnation at 2 iters (not 4), oscillation at A-B-A (not A-B-A-B), double confirmation build
- **I: Schema & Type Fixes** (6) — build_command string→list, module_path, artifact_path_pattern, build_tool_version
- **J: Migration Path** (6) — phased: new modules → fix dead code → CLI flag → extend evaluator → A/B benchmark → cleanup

## Design Tensions Resolved

| Tension | Resolution |
|---------|------------|
| Structured feedback vs full context | Write artifacts to files, structured summary in prompt, Read tool for deep dives |
| Observer pre-pass vs agent-only | Pre-pass stays as data-gathering (not decision-making), feeds Analysis Agent |
| Single variant vs multi-variant | Agent outputs ranked variants, parallel builds |
| Clone vs API-only | Always shallow-clone (--depth 1, ~5s, cost negligible vs build time) |
| Stagnation threshold (4 vs 2) | 2 consecutive with identical values AND rewards |
| Oscillation detection (4 vs 3 iters) | A-B-A pattern (3 data points), compare template values not just scores |

## Recommended Fast Test Subset (7 packages, ~30 min)

| Package | Level | Why |
|---------|-------|-----|
| jackson-databind:2.15.3 | L4 | Regression guard |
| snappy-java:1.1.10.5 | L4 | Multi-iter regression guard |
| jackson-core:2.15.3 | L3 | Cross-package transfer test |
| commons-beanutils:1.9.4 | L3 | Apache flags |
| lz4-java:1.8.0 | L2 | Gradle detection |
| kafka-clients:3.6.1 | L2 | Podman short-name |
| hibernate-core:6.4.2.Final | L1 | Hardest case |

## Open Questions

1. max_iterations: 10 (proposed, no pushback)
2. Sub-agent model: sonnet-4-6 vs opus-4-6 (not discussed)
3. Multi-variant build scheduling on rh-h100 (not detailed)
4. RecipeStore schema changes for ScoreBreakdown (not discussed)
5. Containerfile reverse-parsing for warm-start (mentioned but no implementation detail)
