---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-16
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-16

## Context
- **Cycle**: 10 — targeted single-item cycle for issue #27
- **Trigger**: Agent architecture gaps identified in exp 9 benchmark (7/31 = 22.6% L4 solve rate)
- **Current Score**: ~0.845 (composite: 0.5651)
- **Keep Streak**: 9/9

## CEO Verdict
**PROCEED** — 1 hypothesis covering all 6 priorities (P1-P6) as one coherent EXPLORE/mixed hypothesis with mandatory 31-package benchmark execution.

## Approved Hypothesis

### H1: Agent architecture overhaul — feedback loops, multi-candidate builds, and runtime awareness
- **Category**: EXPLORE
- **Type**: mixed
- **Issue**: #27
- **Priority**: high
- **Target**: L4 solve rate 22.6% → ≥35% (11/31)

### Six Priorities

| Priority | Description | Scope | Expected Impact |
|----------|-------------|-------|----------------|
| P1 | Top-K parallel candidate builds (Gap 4) | `--node-agents` | Multiplicative — K paths per iteration |
| P2 | Per-cycle AnalyzeAgent with ACE-like playbooks (Gaps 1, 2, 5) | `--node-agents` | Core learning loop |
| P3 | Tiered recipe store | `--node-agents` | Checkpoint/skip for solved packages |
| P4 | Spec overrides persistence (Gap 3) | `--node-agents` | Required for P2, fixes kafka-clients smoking gun |
| P5 | Podman docker.io/library/ prefix | Universal | Fixes 5 L2 failures immediately |
| P6 | Reproducible build flags | Universal | Converts 6 L3 → L4 |

### Key Implementation Details
- **P1**: Replace `apply_best()` in `base.py:117-126` with `apply_top_k(spec, candidates, k=3)` returning K (spec, containerfile) pairs
- **P2**: New `AnalyzeAgent` as Claude Code subprocess (`spawn_claude_agent()`, budget $2, timeout 300s), writes append-only DO/DON'T playbook entries to `.factory/playbooks/node_agents/{agent_name}.md` with helpful/harmful counters (ACE pattern from Zhang 2025)
- **P3**: Save recipes at every successful level to `.factory/recipes/{coordinate}.json`
- **P4**: Add `spec_overrides: dict[str, Any]` that persists across iterations, applied after `Observer.observe()` regenerates the spec
- **P5**: In `JdkResolver._map_distribution_to_image()` at `jdk.py:299-304`, always emit `docker.io/library/` prefix
- **P6**: Add `-Dproject.build.outputTimestamp` to Maven, normalize JAR metadata (strip `Built-By`/`Created-By`/timestamps)

### Inner Loop Restructure
- Re-run `observe()` with accumulated spec_overrides on each iteration
- Remove `failure_agent_used` single-fire gate at `loop.py:83`
- Update `should_activate()` in `base.py:93-98` to also activate on spec_overrides fields

### Execution Step
Deploy to rh-h100 nodes via rsync, run full 31-package benchmark (`buildroot agent --batch` split across rh-h100-01 through rh-h100-06+), collect results, compare L4 solve rate against exp 9 baseline (7/31 = 22.6%).

## Anti-patterns
- Don't let Builder rewrite entire Containerfiles — use spec_overrides for surgical updates
- Don't mock E2E runs — 31-package benchmark on rh-h100 mandatory
- Don't fire AnalyzeAgent without early termination — ≥3 consecutive iterations with no level improvement → stop
- Don't repeat error classifier blindness — AnalyzeAgent structured diagnosis replaces `unknown` classification
- Don't break non-agent mode — P1-P4 behind `--node-agents` flag, P5/P6 universal

## Builder Instructions
1. Implement ALL 6 priorities (P1-P6) in single PR
2. P5 and P6 are deterministic fixes — apply universally
3. P1-P4 must be behind `--node-agents` flag
4. After code changes: deploy to rh-h100, run full 31-package benchmark
5. Early termination for AnalyzeAgent: ≥3 stagnant iterations → stop
6. Don't break non-agent mode

## Research Validation
- **ACE framework** (Zhang et al., 2025) — append-only playbooks with helpful/harmful counters
- **CORAL** (2025) — parallel exploration without coordination (3-10x improvement)
- **Chains-Rebuild** (Sharma et al., FSE 2026) — canonicalization converts 26.89% of artifacts; all 6 L3 cases are metadata-only
- **AgentDebug** (Sep 2025) — 26% improvement from targeted corrective feedback
- **Build-bench** — three-input prompt pattern (logs + state + history)

## Five Architectural Gaps Addressed
1. Agents run pre-build only — no failure feedback (`augmented_observer.py:40-72`)
2. `should_activate()` blocks agents from fixing OBSERVED values (`base.py:93-98`)
3. Fixes don't persist across iterations — no spec_overrides mechanism
4. `apply_best()` picks one candidate, discards alternatives (`base.py:117-126`)
5. Failure agents and node agents are disconnected — no shared playbook

## Design Space Assessment
| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | 9 kept experiments, L1→L4 pipeline, inner/outer loops, node agents |
| Bug fixes | 3 | Podman prefix, JDK suffix doubling, ENV syntax |
| Instrumentation | 2 | 60.6% observability but only 19% function coverage |
| Flow changes | 4 | Major arch rewrites across experiments 6-9 |
| New agents | 5 | 13 agents now (10 node + 3 failure); heavily explored |
| Prompt engineering | 2 | Agent prompts not systematically tuned |
| Eval improvements | 2 | L1-L4 scoring exists but error classifier blind |
| Knowledge management | 1 | No playbooks, no recipe store, no cross-run learning |
| Self-evolution | 1 | No feedback loops — agents can't learn |

**Underserved**: Knowledge management, Self-evolution, Prompt engineering — all addressed by this hypothesis.
