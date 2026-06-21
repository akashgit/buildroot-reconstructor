---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-42
  - architecture
source: factory-archivist
date: 2026-06-18
research_type: context
---

# Issue #42 Context Research: Architecture Evolution & Experiment History

## Summary

Synthesized 14 experiments and 5 cross-referenced issues to establish the architectural context for Builder removal. Key conclusion: the AnalyzeAgent concept is validated (exp 10), Builder is quantifiably net-zero, and the L3→L4 frontier requires reproducibility parameters — not Containerfile rewriting.

## Architecture Evolution (6 Layers, 14 Experiments)

1. **Core Pipeline** (exp 1–3): Template-based Containerfile generation with Jinja2
2. **External Validation** (exp 4–5): PNC ground-truth scoring (mean 0.5833)
3. **Agentic Inner Loop** (exp 6): Builder agent introduced — LLM rewrites entire Containerfiles
4. **Intelligent Outer Loop** (exp 7–8): Cross-package learning, Claude Code migration
5. **Node-Scoped Agents** (exp 9): 13 Claude Code reviewers per pipeline step
6. **Pipeline Quality** (exp 10–14): Revert, recovery, critique fixes

**Critical design tension**: Exp 9 implemented the correct architecture (issues #22/#24), but Builder was never removed. Both systems now run — node agents propose structured changes, then Builder overwrites anyway.

## Experiment Learnings Directly Relevant to #42

### Exp 9 (KEEP, -0.001): Node-Scoped Agents
- 13 agents with evidence hierarchy, consistent patterns
- Node agents run ONCE before builds, then Builder takes over — design incompleteness
- `AgentAugmentedObserver` is the correct insertion point for re-observation

### Exp 10 (REVERT, -19.4pp): AnalyzeAgent + Top-K
- **AnalyzeAgent concept validated** — worked when it fired
- Failure was early termination (`consecutive_no_improvement >= 3`), NOT the agent itself
- Cherry-pickable: Podman prefix fix, AnalyzeAgent design, Top-K candidates

### Exp 12 (KEEP, +0.025): Elitist Gate
- Fixed exp 10's catastrophe: checkpoint-and-restore replaces early termination
- Now baseline infrastructure that issue #42 builds on

### Exp 13 (KEEP, +0.2900): Pipeline Critique Fixes
- Added L3/L4 error patterns, SOURCE_DATE_EPOCH, dead-end expansion
- Second-largest single-experiment gain — information flow > individual stage sophistication

## Data-Backed Systemic Findings

### Builder Never Achieved L4
- 0/8 L4 successes came from Builder — ALL came from initial observation/template
- Builder consumed 89% of iterations (322/363) at ~$2-5 per opus invocation
- Net-zero improvement: 7 improvements, 7 regressions (oscillation)

### Top-K Re-Observation Oscillation
- 49 regressions vs 53 improvements in mini-benchmark
- All 10 node agents re-run each iteration with different LLM outputs
- Fix needed: Lock parameters that achieved a level, only re-run flagged dimensions

### Dead-End Registry Too Coarse
- Jackson-core: 26 exhausted entries — whole-file signatures
- System doesn't learn that individual parameters work; tracks entire Containerfiles

### L3→L4 Is the Real Frontier

| Package | Structural | Metadata | Bytecode | Issue |
|---------|-----------|----------|----------|-------|
| jackson-core | no | yes | no | JDK/compiler mismatch |
| commons-beanutils | no | no | yes | Extra/missing files + metadata |
| assertj-core | no | no | no | Fundamental mismatch |
| kafka-clients | no | yes | no | JDK/compiler mismatch |
| json-path | no | yes | yes | ONLY structural — extra/missing entries |

5/6 L3 packages build fine but JAR doesn't match. Builder can't help — Containerfile is correct enough. Problem is reproducibility parameters (exact JDK minor, build flags, resource filtering).

## Prior Design Decisions Leading to #42

- **Issue #22**: "LLM never touches the Containerfile directly" — the foundational design contract. Builder violates it.
- **Issue #24**: 10-node + 3-failure agent architecture — structured output, evidence citations
- **Issue #27**: Identified 5 structural gaps; designed AnalyzeAgent to bridge failure → spec_overrides → re-observation

### Key Insight from Issue #27 Research
> "Two Disconnected Fix Systems: Node agents (pre-build) and Builder (post-build) operate independently. The Builder doesn't know which node agent made which decision."

Issue #42 solves this by removing Builder and giving AnalyzeAgent the Builder's capabilities via structured spec_overrides.

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|-----------|
| Regression on snakeyaml (only L4 in mini-benchmark) | High | Snakeyaml reached L4 via initial observation, not Builder |
| Missing edge cases in template injection | High | Builder handled ~8 build system misdetection cases |
| AnalyzeAgent prompt complexity (3-tier vocabulary) | Medium | Opus upgrade helps |
| Template injection ordering errors | Medium | Test all 4 templates |
| Builder removal itself | Low | Data shows net-zero; --legacy-builder flag provides rollback |

## Benchmark Baseline
- L4 solve rate: 7/31 (22.6%) — exp 9 baseline
- Composite score: 0.7948 — post-exp-13
- snakeyaml: L4 (reward=1.00) in mini-benchmark
- Acceptance criteria: snakeyaml still L4, 5 L3 packages still L3, iteration count comparison
