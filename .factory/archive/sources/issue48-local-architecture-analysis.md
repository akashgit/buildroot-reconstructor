---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-48
source: factory-archivist
date: 2026-06-19
---

# Issue #48 Local Research — Codebase Architecture Analysis

## Two Parallel Pipeline Paths

The codebase has two pipeline implementations:

**Path A — "Standard Loop" (`agent/loop.py`)**: `Observer → GapDetector → 11 NodeAgents → AnalyzeAgent → Evaluator` loop. Uses `spec_overrides` dict applied to `BuildrootSpec`. Has elitist gate, dead-end tracking, warm-start from RecipeStore.

**Path B — "Pipeline v2" (`agent/pipeline_v2.py`)**: `Observer → clone repo → AnalysisAgent (Read+Bash tools) → Build → Evaluate → FailureAgent` loop. Single analysis agent replaces 11 node agents. Returns structured JSON matching `BUILDROOT_SCHEMA`. **This is the issue #48 direction.**

## Component Inventory (Issue #48 Impact)

| Component | LOC | Verdict |
|-----------|-----|---------|
| Observer | 73 | **Keep** — renamed to "pre-pass" |
| AgentAugmentedObserver | 273 | **Remove** |
| GapDetector | 199 | **Remove** — agent sees gaps directly |
| 11 Node Agents | ~1800 | **Remove** |
| AnalyzeAgent | ~100 | **Replace** with unified analysis agent |
| Evaluator | 290 | **Keep** |
| ContainerfileGenerator | 275 | **Keep** |
| Inner Loop (loop.py) | 659 | **Replace** with simplified loop |
| Outer Loop | 609 | **Keep** |
| RecipeStore | ~90 | **Keep** |
| Pipeline v2 | 570 | **This IS the proposal** |
| Claude Runner | 177 | **Keep** |
| Error Classifier | ~400 | **Keep** (deterministic analysis) |

## Pipeline v2 — What Exists vs What's Missing

v2 already implements: deterministic observer pre-pass, local repo clone, JAR download, single analysis agent with tools, failure analysis agent, template rendering, build→evaluate→adjust loop.

**13 features missing from v2 vs full issue #48 spec:**
1. `PrePassFindings` structured data model (passes raw dict instead)
2. `attempted_but_failed` tracking
3. Confidence + source per field
4. Elitist gate (exists in v1, not v2)
5. Dead-end tracking (exists in v1, not v2)
6. Rendered Containerfile in feedback
7. Cross-package knowledge transfer
8. Template-value diffs between iterations
9. Warm-start from RecipeStore (only checks L4 cache)
10. Parallel first build + analysis
11. Multiple variants per iteration
12. Double confirmation build
13. Score/reward history in feedback

## Test Suite

- **498 unit tests**, all mocked (no SSH, no Claude, no builds)
- Runs in **~0.1 seconds**
- **Zero E2E tests** in repo — E2E requires `rh-h100-01` with real podman builds
- Best E2E smoke test candidates: jettison:1.5.4 (7 min, L4), plexus-utils:4.0.0 (7 min, L4), json:20231013 (9 min, L4)

## Benchmark State

- 31 packages total, **9 L4 solved (29%)**, 6 L3, 12 L2, 4 L1
- L1: 100%, L2: 94%, L3: 45%, L4: 29%
- Biggest bottleneck: L3→L4 transition (14 packages build but JARs diverge)
- Total serial run time: ~29 hours

## Key Architectural Finding

**Start from `pipeline_v2.py`**, not v1. It has the right architecture. Port the missing features from v1 (elitist gate, dead-ends, warm-start) rather than adding v2 features to v1.
