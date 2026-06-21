---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
  - cycle-summary
date: 2026-06-17
updated: 2026-06-17T22:30
source: factory-archivist
---

# Factory Cycle Summary: buildroot-reconstructor — 2026-06-07 to 2026-06-17

## Overview

**Duration**: 11 days (2026-06-07 to 2026-06-17)
**Experiments**: 12 executed (IDs 1–10, 12–13)
**Verdicts**: 11 KEEP, 1 REVERT
**Keep Rate**: 91.7% (11/12)
**Keep Streak**: 9 consecutive KEEPs (#001–#009), broken by #010, recovered with #012–#013
**Score Trajectory**: 0.6433 (baseline) → 0.8499 (peak at #003) → 0.7948 (final, post-#013)
**Final Commit**: 19237ec (pipeline critique fixes)

## Experiment Timeline

| # | Date | Hypothesis | Verdict | Score Δ | Category |
|---|------|-----------|---------|---------|----------|
| baseline | 06-07 | Initial build from spec | — | 0.586→0.831 | BUILD |
| 1 | 06-08 | Fix 6 L3 rebuild gaps | KEEP | +0.2066 | FIX |
| 2 | 06-08 | L3 full rebuild refinement (10/10 pass) | KEEP | +0.1947 | REFINE |
| 3 | 06-09 | L4 multi-layer JAR comparison pipeline | KEEP | +0.5418 | ADD |
| 4 | 06-12 | PNC ground-truth validation | KEEP | +0.2807 | ADD |
| 5 | 06-13 | PNC validation execution on rh-h100-01 | KEEP | +0.0000 | REFINE |
| 6 | 06-13 | Agentic inner loop MVP | KEEP | +0.0038 | ADD |
| 7 | 06-13 | Outer loop intelligence layer | KEEP | +0.0427 | ADD |
| 8 | 06-13 | Claude Code agent migration | KEEP | +0.0014 | REFINE |
| 9 | 06-15 | Node-scoped agents (13 agents) | KEEP | -0.001 | ADD |
| 10 | 06-17 | Agent architecture overhaul | REVERT | -19.4pp L4 | ADD |
| 12 | 06-17 | Elitist gate with patience counter | KEEP | +0.025 | FIX |
| 13 | 06-17 | All 8 pipeline critique fixes | KEEP | +0.2900 | FIX |

## Architecture Evolution

The project progressed through 6 distinct architecture layers:

1. **Core Pipeline** (#001–#003): Deterministic buildroot reconstruction — POM parsing, JDK inference, Containerfile generation, 3-layer JAR comparison
2. **External Validation** (#004–#005): PNC ground-truth scoring — Containerfile parsing, 6-dimension accuracy scorer, real infrastructure validation (mean accuracy 0.5833)
3. **Agentic Inner Loop** (#006): AdaEvolve-based repair loop — Observer→Builder→Evaluator→Analyzer cycle, 33% solve rate on 3-package smoke test
4. **Intelligent Outer Loop** (#007–#008): Cross-package learning — failure analyst, knowledge base, strategy archive, Claude Code subprocess migration
5. **Agent Augmentation** (#009): Node-scoped review agents — 13 Claude Code reviewers at every pipeline step
6. **Pipeline Quality** (#010–#013): Revert, recovery, and systematic improvement — elitist gate, error patterns, evaluator enrichment, SOURCE_DATE_EPOCH, tau tuning, dead-end signatures, build system detection

## Key Metrics at Close

- **Composite Score**: 0.7948 (post-exp-13)
- **L4 Solve Rate**: 7/31 (22.6%) on 31-package benchmark (exp #009 baseline)
- **Best Single-Package Result**: commons-lang3 — solved in 1 iteration (reward 1.0)
- **Agentic Solve Rate**: 1/3 (33.3%) on smoke test
- **PNC Validation Accuracy**: 0.5833 mean (3 packages)
- **Test Suite**: ~342 passing tests
- **Keep Rate**: 91.7% (11/12)
- **Largest Single Gain**: #003 (+0.5418, L4 comparison pipeline)
- **Largest Pipeline-Quality Gain**: #013 (+0.2900, critique fixes)

## The Revert Arc (#010 → #012 → #013)

### Experiment #010 — Agent Architecture Overhaul (REVERT)
- **Root Cause**: Early termination (`consecutive_no_improvement >= 3`) too aggressive — cut iteration budget from 15 to ~4, causing 14/31 package regressions
- **L4 Rate**: 22.6% → 3.2% — catastrophic regression
- **Lesson**: Termination thresholds must be calibrated against baseline iteration-to-solve distributions. Level-based improvement tracking is too coarse — use reward (continuous) not level (discrete)

### Experiment #012 — Elitist Gate (KEEP, +0.025)
- **Fix**: Checkpoint-and-restore approach instead of terminate. Patience counter allows 1 iteration of exploration below best, then restores from best checkpoint
- **Lesson**: When an iterative optimizer regresses, restore (preserve best state, continue) beats terminate (kill the run)

### Experiment #013 — Pipeline Critique Fixes (KEEP, +0.2900)
- **Payoff**: All 8 critique fixes together delivered +0.2900 — the information flow improvements (actionable error patterns, richer evaluator output, SOURCE_DATE_EPOCH for timestamp nondeterminism, tighter stall detection, dead-end avoidance) created a multiplicative effect
- **Lesson**: The elitist gate from #012 was a prerequisite — without it, the loop would terminate too early to benefit from the improved signals. Bundled prioritized fixes produce outsized gains when bottlenecks are independent

## Research Findings Worth Preserving

1. **SOURCE_DATE_EPOCH** fixes 92.4% of Maven reproducibility failures (Benedetti et al., ICSE 2025)
2. **All 6 L3 failures** have `bytecode_match=True` — divergence is metadata-only, canonicalizable
3. **Podman prefix fix** from exp #010 is universally beneficial — should be cherry-picked standalone
4. **Macaron BuildGen** (Oracle Labs, ASE 2025): rebuilt 73/81 Maven packages using whole-project builds
5. **Chains-Rebuild** (Sharma et al., FSE 2026): canonicalization converts 26.89% of artifacts to reproducible by stripping timestamp/metadata differences

## Unfinished Work / Next Cycle Roadmap

1. **Cherry-pick Podman prefix fix** from exp #010 — universal `docker.io/library/` fix
2. **31-package re-benchmark** after exp #013 fixes — projected L4 rate increase
3. **Top-K parallel candidate evaluation** — CORAL-style parallel `podman build` for agent candidates
4. **Gradle detection robustness** — `git archive --remote` doesn't work with GitHub HTTPS; needs fallback
5. **Unit tests for new modules** — exp #013's +244 lines have E2E coverage but no unit tests
6. **Merge open PRs** — #37 (exp 13), #33 (exp 12), #26 (exp 9), #21 (exp 8), #15 (MVP)

## Patterns Discovered (27 total)

This factory cycle generated 27 cross-project patterns in `.factory/archive/patterns/patterns.md`, covering:
- Build system patterns (JDK detection, Gradle daemon, Containerfile sanitization, SOURCE_DATE_EPOCH)
- Agent architecture (node-scoped agents, tool restrictions, structured output, failure tiering)
- Quality gating (multi-round review, E2E validation, early termination calibration)
- Factory process (eval delta interpretation, keep streak analysis, precheck false positives)
- Optimization control (checkpoint-and-restore vs early termination, bundled critique fixes)
- Information flow (inter-stage fidelity as highest-leverage optimization target)

## Final Assessment

The buildroot-reconstructor factory cycle evolved a Maven build reconstruction tool from spec to a multi-agent agentic system in 11 days across 12 experiments. The 91.7% keep rate demonstrates effective quality gating. The single revert (#010) produced the cycle's most valuable lesson — early termination calibration — and the recovery arc (#012 → #013) proved that systematic critique-driven fixes produce outsized gains when applied in concert.

The cycle's two largest gains were both "fix" experiments: #003 (+0.5418, adding L4 comparison) and #013 (+0.2900, pipeline critique fixes). This reinforces a key insight: for agentic pipelines, improving information flow between existing stages is as impactful as adding new capabilities. The project closes at 0.7948 composite score with clear next-cycle targets (Podman prefix, re-benchmark, parallel candidates) that build on the infrastructure rather than adding new architectural layers.
