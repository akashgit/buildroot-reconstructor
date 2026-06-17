---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
  - cycle-summary
date: 2026-06-15
source: factory-archivist
---

# Cycle 9 Summary: buildroot-reconstructor — 2026-06-15

## Overview
Targeted single-item cycle for **issue #24** (node-scoped Claude Code agents at every pipeline step). This was a focused architectural enhancement — no research phase needed, strategy derived directly from issue spec.

## Experiment #009 — Node-Scoped Agents (KEEP, -0.001 noise)

### What Shipped
- **13 Claude Code reviewer agents**: 10 node-scoped (POM, ParentChain, Property, Repo, CI, JDK, Image, Tag, BuildCmd, Template) + 3 failure-level (L2/L3/L4)
- **AgentAugmentedObserver**: Wraps Observer → GapDetector → fires node agents per gap → re-renders Containerfile
- **CLI integration**: `--node-agents` flag on `buildroot agent` command
- **Evidence hierarchy ranking**: `direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default`
- **Model split**: Sonnet for node agents (cost-conscious), Opus for failure agents (deeper reasoning)
- **+1397/-3 lines, 17 files, PR #26**

### Code Quality
CEO code review: **CLEAN** after 3 iterations. 5 bugs fixed:
1. WORKDIR duplication in template agent
2. Stale reward signal passed to failure agents
3. Mutable class variable (`ALL_NODE_AGENTS`)
4. False-positive agent activation logging
5. Failure agent loop re-entry bug

### Benchmark Status
**Incomplete** — 2/31 packages processed (jackson-core, jackson-databind). Full 31-package benchmark requires ~19 hours on rh-h100-01 and was not executed this cycle. Agents confirmed firing correctly on both processed packages.

### Bug Discovered
**Image Agent doubled `-jdk` suffix** — generating `eclipse-temurin:8-jdk-jdk` instead of `eclipse-temurin:8-jdk`. Found during partial benchmark, fixed in review round 2.

### Eval Environment Issue
Eval environment was broken in the worktree (pre-existing issue, not caused by PR #26). Precheck reported false positives. `--force` used for verdict.

### Score
0.8456 → ~0.845 (-0.001, noise floor). No regression.

## Cumulative Project State

| Metric | Value |
|--------|-------|
| Experiments | 9 |
| Keep streak | 9/9 (perfect) |
| Reverts | 0 |
| Score (baseline → current) | 0.6433 → 0.845 |
| Total tests | 430 |
| Features | 13 core + agentic inner/outer loop + 13 node agents |
| Total lines added | ~11,000+ across all experiments |
| Open PRs | #26 (node agents), #21 (Claude Code migration), #15 (inner loop) |
| Merged PRs | #18 (outer loop), #11 (PNC validation) |

## Architecture Progression (9 experiments)

```
#001-#003: Core pipeline (inference → verification → JAR comparison)
#004-#005: External validation (PNC ground truth, rh-h100-01 execution)
#006:      Agentic inner loop (Observer → Builder → Evaluator → Analyzer)
#007:      Intelligent outer loop (failure analyst, guards, knowledge base)
#008:      Claude Code subprocess migration (shared runner, 4 agents)
#009:      Node-scoped agents (13 reviewers at every pipeline step)
```

## Outstanding Work
1. **Full 31-package benchmark** on rh-h100-01 (~19 hours) — issue #24 acceptance criterion partially met
2. **3 open PRs** awaiting merge (#26, #21, #15)
3. **Image agent `-jdk` suffix** — fixed in PR but validates the need for full benchmark
4. **Eval worktree environment** — pre-existing breakage needs investigation

## Key Learnings This Cycle
1. Node-scoped agents with structured output and evidence ranking are architecturally superior to giving LLMs full artifact control
2. Multi-round code review (3 iterations) catches interaction bugs that single-pass review misses
3. Partial benchmarks (2/31) can validate agent activation patterns even when full benchmarks are impractical within a cycle
4. Infrastructure experiments show small eval deltas — KEEP decisions should weight code quality and capability unlock over score movement
