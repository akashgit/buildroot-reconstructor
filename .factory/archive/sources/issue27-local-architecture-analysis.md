---
tags:
  - factory
  - source
  - issue-27
source: factory-archivist
date: 2026-06-16
---

# Issue #27 Local Architecture Analysis — Code-Level Gap Mapping

## Pipeline Data Flow

```
run_inner_loop() → Observer.observe() → [AgentAugmentedObserver] → GapDetector → NodeAgents → Containerfile
  └── for t in range(max_iterations):
      ├── evaluator.evaluate() → EvalResult
      ├── [t==0 only] run_failure_agents()
      ├── analyzer.analyze() → AnalysisResult
      └── builder.refine/explore/fresh_start
```

## Two Disconnected Fix Systems

1. **Node agents** (pre-build): `augmented_observer.py` — review spec fields, propose candidates, `apply_best()` picks one. Run ONCE before any builds.
2. **Inner loop builder** (post-build): `loop.py:84-195` — on failure, Builder rewrites entire Containerfile. Uses analyzer.py for error classification but NOT the node agent system.

The Builder doesn't know which node agent made which decision, can't update the spec, and can't leverage alternative candidates.

## Five Gaps Confirmed with Code Locations

| Gap | Code Location | Evidence |
|-----|--------------|----------|
| 1. No failure feedback | `augmented_observer.py:40-72` — observe() called once | kafka-clients repeats same Podman error 15x |
| 2. should_activate() blocks OBSERVED | `base.py:93-98` — only DEFAULTED/INFERRED | lz4-java Maven vs Gradle stuck 15 iterations |
| 3. Fixes don't persist | `loop.py:84-195` — no spec_overrides | docker.io/library/ prefix never sticks |
| 4. apply_best() discards alternatives | `base.py:117-126` — sorted, picks rank-0 | jackson-core 3 approaches tried sequentially |
| 5. Failure/node agents disconnected | `failure_agents.py` vs `node_agents/base.py` | No shared playbook |

## Implementation Impact (P1-P6)

| Priority | Files Changed | Complexity |
|----------|--------------|-----------|
| P1 (Top-K) | base.py, augmented_observer.py, loop.py, models.py | High |
| P2 (AnalyzeAgent) | New analyze_agent.py, loop.py, augmented_observer.py, base.py | Medium |
| P3 (Recipes) | models.py, loop.py | Low-Medium |
| P4 (Spec overrides) | loop.py, augmented_observer.py | Low |
| P5 (Podman prefix) | generators/containerfile.py | Very Low |
| P6 (Reproducible flags) | generators/containerfile.py, jar_comparator.py | Low |

## Recommended Order (Local Analysis)

P5 → P4 → P2 → P3 → P6 → P1 (impact-first, complexity-ascending). P5+P4+P6 alone could push from 7/31 to ~15/31 L4.
