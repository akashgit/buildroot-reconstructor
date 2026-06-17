---
tags:
  - factory
  - project
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
updated: 2026-06-17T12:00
---


# Factory: Buildroot Reconstructor

## Status
- **State**: CYCLE 10 COMPLETE — REVERT — early termination regression, PR #29 closed
- **Active Issue**: #27 — Agent architecture: fix feedback loops, multi-candidate builds, and runtime awareness (REVERTED)
- **Cycle**: 10 — COMPLETE (REVERT)
- **Strategy Approved**: 2026-06-16 — H1: Agent architecture overhaul (P1-P6), EXPLORE/mixed, high priority
- **Current Score**: ~0.845 (unchanged — reverted to exp #009 state)
- **Composite Score**: 0.5651
- **Agentic Solve Rate**: 1/3 (33.3%) — commons-lang3 solved in 1 iteration, micrometer-core reached L2, spring-security-core stuck at L1
- **PNC Validation Score**: 0.5833 mean accuracy (3 packages, range 0.325–0.750)
- **Pre-Experiment #010 Score**: ~0.845
- **Pre-Experiment #009 Score**: 0.8456 (composite: 0.5651)
- **Pre-Experiment #008 Score**: 0.8442
- **Pre-Experiment #007 Score**: 0.8012
- **Pre-Experiment #006 Score**: 0.5662
- **Baseline Score**: 0.6433 (pre-experiment #001)
- **Experiments Run**: 10
- **Kept**: 9, **Reverted**: 1
- **Last Experiment**: #010 — Agent architecture overhaul (REVERT, -19.4pp L4 rate regression, 1/31 vs 7/31 baseline)
- **Previous Experiment**: #009 — Node-scoped agents: 13 Claude Code reviewers (KEEP, -0.001 noise)
- **Total Tests**: 342/343 passing (no new tests for core classes — benchmark is primary validation)
- **Active Strategy**: Issue #27 — Agent architecture overhaul: H1 approved (P1-P6), EXPLORE/mixed, high priority. REVERTED after 31-package benchmark showed severe regression. Root cause: early termination threshold too aggressive.
- **Previous Strategy**: Issue #24 — Node-scoped pipeline agents (KEEP, 9/9 streak)
- **Open PRs**: #29 — Agent architecture overhaul (CLOSED/REVERTED), #26 — Node-scoped agents, #21 — Claude Code agent migration, #15 — Inner loop MVP
- **Merged PRs**: #18 — Outer loop intelligence layer, #11 — PNC ground-truth validation
- **Keep Streak**: 0 (BROKEN at 9 — experiment #010 reverted)

## Experiment #010 Post-Mortem: Early Termination Regression

### The Problem
Early termination at `loop.py:300-315` (`consecutive_no_improvement >= 3`) terminates packages after ~4 iterations. The baseline ran all 15 iterations. This cut exploration budget by ~73%, causing 14/31 packages to regress.

### Root Cause
The termination counter tracks **level** improvement only (L1→L2→L3→L4), not **reward** improvement (0.05→0.14 within L1). Packages that need many attempts to break through level boundaries register as "no improvement" and get terminated before they can reach L4.

### What Should Be Preserved
- **P5 (Podman prefix)** — Universal fix for docker.io/library/ issue. Should be cherry-picked.
- **P2 (AnalyzeAgent)** — Worked when it fired. Needs more iterations to be useful.
- **P1 (Top-K)** — Generated candidates correctly. Needs iteration budget to explore them.

### Recommendation for Next Cycle
1. Remove early termination entirely, or raise threshold to ≥8
2. Track reward improvement, not just level
3. Cherry-pick P5 (Podman prefix) as a standalone fix
4. Retest P1/P2 with full 15-iteration budget

## PNC Ground-Truth Validation Results (Experiment #005)

| Package | Accuracy | JDK | Build Tool | Maven Version | Key Issue |
|---------|----------|-----|------------|---------------|-----------|
| commons-lang3:3.14.0 | 0.325 | MISS (21 vs 8) | ✓ | ✓ | Build-Jdk-Spec=21 is upstream CI's JDK, not PNC's |
| jackson-core:2.17.0 | 0.750 | HIT (8) | ✓ | ✓ | Best result — all major dimensions matched |
| snakeyaml:2.2 | 0.675 | HIT (11) | ✓ | MISS | Maven version extraction missing (empty string) |
| **Mean** | **0.5833** | | | | |

### Key Findings
1. Build-Jdk-Spec in JAR manifests reports upstream CI's JDK, not PNC's build JDK
2. OS family extraction returns empty across all packages — needs improvement
3. SCM URL scoring gives partial credit (0.5) when ground truth is empty
4. Maven version not extracted from all available sources (snakeyaml gap)

## Agentic Smoke Test Results (Experiment #006)

| Package | Status | Best Reward | Iterations | Elapsed |
|---------|--------|-------------|------------|---------|
| commons-lang3:3.14.0 | **SOLVED** | 1.0 | 1 | 741s |
| micrometer-core:1.10.13 | budget_exhausted | 0.15 (L2) | 15 | 974s |
| spring-security-core:5.8.9 | budget_exhausted | 0.05 (L1) | 15 | 681s |
| **Aggregate** | **1/3 solved** | **0.40 mean** | **10.3 avg** | **2395s total** |

## Latest Eval (0.8456 — post experiment #008 KEEP, score_before=0.8442)
| Dimension | Score | Weight | Status |
|-----------|-------|--------|--------|
| tests | 1.000 | 0.15 | all passing (430 total, 29 new in #008) |
| lint | 1.000 | 0.075 | clean |
| type_check | ~0.8+ | 0.05 | pre-existing mypy errors outside scope |
| coverage | 0.980 | 0.125 | 98% |
| guard_patterns | 1.000 | 0.05 | passing |
| capability_surface | 0.306+ | 0.125 | 13 features + claude_runner infrastructure |
| observability | 0.341 | 0.09 | improved from 0.091 |
| research_grounding | 0.320 | 0.07 | 60+ sources (10 new agentic) |

## Recent Experiments

### Experiment #010 — Agent architecture overhaul: AnalyzeAgent, Top-K builds, tiered recipes (REVERT, -19.4pp L4)
- **Hypothesis**: Implement 6 architecture priorities (P1-P6) from issue #27 to close feedback loops, enable multi-candidate builds, and add runtime awareness
- **Benchmark**: 1/31 L4 (3.2%) vs baseline 7/31 L4 (22.6%) — SEVERE REGRESSION
- **Root cause**: Early termination (`consecutive_no_improvement >= 3`) kills packages after ~4 iterations vs baseline's 15
- **PR**: #29 (CLOSED), +715/-47 lines, 13 files
- **Improvements**: 4 packages (commons-lang3 L1→L3, json-path L1→L3, junit L1→L3, logback-classic L1→L2)
- **Regressions**: 14 packages (jackson-databind L4→L3, avro L4→L1, snakeyaml L4→L1, snappy-java L4→L1, etc.)
- **Verdict**: **REVERT** — early termination too aggressive, 9-experiment keep streak broken
- **Details**: `experiments/buildroot-reconstructor-010.md`

### Experiment #009 — Node-scoped agents: 13 Claude Code reviewers at every pipeline step (KEEP, -0.001 noise)
- **Hypothesis**: Implement 13 Claude Code reviewer agents (10 node + 3 failure) integrated into the deterministic pipeline
- **Score**: 0.8456 → ~0.845 (-0.001, noise floor)
- **PR**: #26 (OPEN), +1397/-3 lines, 17 files
- **Verdict**: **KEEP** — code quality CLEAN, architectural completeness confirmed
- **Details**: `experiments/buildroot-reconstructor-009.md`

### Experiment #008 — Claude Code agent migration: shared runner, 4 agents migrated (KEEP, +0.0014)
- **Hypothesis**: Replace all 3 raw `AnthropicVertex` single-shot API calls with Claude Code subprocess agents
- **Score**: 0.8442 → 0.8456 (+0.0014)
- **PR**: #21 (OPEN), +3120/-39 lines, 26 files
- **Verdict**: **KEEP** — clean code review, infrastructure enabler
- **Details**: `experiments/buildroot-reconstructor-008.md`

### Experiment #007 — Intelligent outer loop with failure analyst, guards, strategy archive (KEEP, +0.0427)
- **Hypothesis**: Implement outer loop intelligence: failure analysis, knowledge base, safety guards, J(S) strategy scoring
- **Score**: 0.8012 → 0.8439 (+0.0427)
- **PR**: #18 (MERGED), +2258/-13 lines, 20 files
- **Verdict**: **KEEP** — score +0.0427, all subsystems functional
- **Details**: `experiments/buildroot-reconstructor-007.md`

### Experiment #006 — Agentic reconstructor inner loop MVP (KEEP, +0.0038, validated on rh-h100-01)
- **Score**: 0.5662 → 0.5700 (+0.0038)
- **Verdict**: **KEEP** — 8 modules shipped, inner loop validated end-to-end
- **Details**: `experiments/buildroot-reconstructor-006.md`

### Experiment #005 — PNC validation execution on rh-h100-01 (KEEP, operational refinement)
- **Results**: mean accuracy 0.5833 (3 packages)
- **Verdict**: **KEEP** — pipeline validated against real infrastructure
- **Details**: `experiments/buildroot-reconstructor-005.md`

### Experiment #004 — PNC ground-truth validation (KEEP, +0.2807)
- **Score**: 0.5436 → 0.8243 (+0.2807)
- **Verdict**: **KEEP** — 5 deliverables shipped
- **Details**: `experiments/buildroot-reconstructor-004.md`

### Experiment #003 — Level 4 multi-layer JAR comparison pipeline (KEEP, +0.5418)
- **Score**: 0.3082 → 0.8500 (+0.5418)
- **Verdict**: **KEEP** — comparison pipeline complete
- **Details**: `experiments/buildroot-reconstructor-003.md`

### Experiment #002 — Level 3 build verification refinement (KEEP, 3/10 → 10/10 builds)
- **Verdict**: **KEEP** — build pass rate 30% → 100%
- **Details**: `experiments/buildroot-reconstructor-002.md`

### Experiment #001 — Fix all 6 Level 3 rebuild gaps (KEEP, +0.2066)
- **Verdict**: **KEEP** — score gain +0.2066
- **Details**: `experiments/buildroot-reconstructor-001.md`

### Baseline — Initial Build (ESTABLISHED)
- **Score**: 0.586 → 0.831 (via post-build fixes)
- **Details**: `experiments/buildroot-reconstructor-baseline.md`

## Vision

Reconstruct the complete build environment (buildroot) for a Maven artifact as a Containerfile, working only from the package's `pom.xml` and its CI workflow — enabling consumer-side build provenance reconstruction for supply chain security.

## Architecture

- **Language**: Python 3.11+
- **CLI Framework**: `click`
- **Core Libraries**: `lxml`, `defusedxml`, `ruamel.yaml`, `jinja2`, `dockerfile-parse`, `requests`, `pytest`
- **Container Runtime**: Podman (default), Docker/Buildah supported via `--runtime`
- **Storage**: Filesystem only — POM cache in `~/.cache/buildroot/poms/`

## CLI Commands

- `buildroot reconstruct <coordinate>` — full pipeline → Containerfile + buildroot.json + dependency-tree.json
- `buildroot verify <coordinate>` — validate against JAR manifest, optional rebuild
- `buildroot inspect <coordinate>` — diagnostic: parent chain, properties, JDK inference, CI config
- `buildroot compare <coordinate>` — three-layer JAR comparison against Maven Central original
- `buildroot validate <coordinate>` — compare reconstruction against PNC ground truth

## Strategy History

- `strategies/buildroot-reconstructor-2026-06-07.md` — Initial inception strategy
- `strategies/buildroot-reconstructor-2026-06-07-build-plan.md` — CEO-approved 11-phase build plan
- `strategies/buildroot-reconstructor-2026-06-08-build-complete.md` — Build completion snapshot
- `strategies/buildroot-reconstructor-2026-06-08-level3.md` — Level 3 gaps strategy
- `strategies/buildroot-reconstructor-2026-06-08-cycle-summary.md` — Cycle 2 summary
- `strategies/buildroot-reconstructor-2026-06-09-level4.md` — Level 4 artifact comparison strategy
- `strategies/buildroot-reconstructor-2026-06-09-cycle-summary.md` — Cycle 3 summary
- `strategies/buildroot-reconstructor-2026-06-12-pnc-validation.md` — PNC ground-truth validation strategy
- `strategies/buildroot-reconstructor-2026-06-12-cycle-summary.md` — Cycle 4 summary
- `strategies/buildroot-reconstructor-2026-06-13-cycle-summary.md` — Cycle 5 summary
- `strategies/buildroot-reconstructor-2026-06-13-agentic-inner-loop.md` — Cycle 6 strategy
- `strategies/buildroot-reconstructor-2026-06-13-outer-loop.md` — Cycle 7 strategy
- `strategies/buildroot-reconstructor-2026-06-13-final-cycle-summary.md` — Final cycle summary (7/7)
- `strategies/buildroot-reconstructor-2026-06-13-claude-code-migration.md` — Cycle 8 strategy
- `strategies/buildroot-reconstructor-2026-06-13-complete-cycle-summary.md` — Complete cycle summary (8/8)
- `strategies/buildroot-reconstructor-2026-06-15-node-scoped-agents.md` — Cycle 9 strategy
- `strategies/buildroot-reconstructor-2026-06-15-builder-complete.md` — Cycle 9 builder snapshot
- `strategies/buildroot-reconstructor-2026-06-15-cycle-summary.md` — Cycle 9 summary
- `strategies/buildroot-reconstructor-2026-06-16-agent-architecture-overhaul.md` — Cycle 10 strategy (REVERTED)
- `strategies/buildroot-reconstructor-2026-06-17-cycle-summary.md` — Cycle 10 summary (REVERT, first revert in 10 experiments)
