---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-07
phase: build-plan
verdict: APPROVED
source: factory-archivist
---

# Strategy: Buildroot Reconstructor — 2026-06-07 (CEO-Approved Build Plan)

## Verdict

**PLAN APPROVED** — CEO reviewed and confirmed all 9 core features from the approved spec are present. No scope cuts. No new deferrals. 100% feature coverage confirmed.

## CEO Issues Noted

- Phase 11 verification levels must align with pre-mortem E2E levels:
  - **Level 1** (inference correctness): Containerfile syntactically valid, correct base image, correct build command, buildroot.json complete, JAR manifest Build-Jdk-Spec cross-reference
  - **Level 2** (container builds): `podman build` must succeed on at least 2-3 generated Containerfiles — verifies the container actually builds, not just syntactic validity
  - **Level 3** (full rebuild): Deferred per spec

## Build Plan Summary

11 phases in dependency order, each scoped to one PR.

### Dependency Graph

```
Phase 1 (scaffold)
  ├── Phase 2 (POM parsing)
  │     └── Phase 3 (property resolution)
  │           └── Phase 5 (JDK inference) ←── Phase 4 (CI parsing)
  │                                              └── Phase 6 (container images)
  ├── Phase 4 (CI parsing) [independent of POM]
  ├── Phase 7 (transitive deps) [needs Maven + POM]
  ├── Phase 8 (Containerfile gen) [needs Phases 3-6]
  ├── Phase 9 (gap detection) [needs all extractors]
  ├── Phase 10 (pipeline + CLI) [needs all components]
  └── Phase 11 (test harness) [needs everything]
```

### Approved Phase Order

1. Phase 1: Scaffold + prerequisites + eval harness
2. Phase 2: POM fetching + parent resolution
3. Phase 3: Property placeholder resolution
4. Phase 4: CI workflow parsing
5. Phase 5: JDK version inference
6. Phase 6: Container image resolution
7. Phase 7: Transitive dependency tree
8. Phase 8: Containerfile generation
9. Phase 9: Gap detection + confidence
10. Phase 10: Pipeline orchestration + CLI
11. Phase 11: Test harness with Level 1 + Level 2 verification

### Feature Coverage Matrix

| # | Core Feature | Phase(s) |
|---|---|---|
| 1 | POM Fetching and Parsing with Full Parent Resolution | Phase 2 |
| 2 | Maven Property Placeholder Resolution | Phase 3 |
| 3 | CI Workflow Parsing (GitHub Actions + CircleCI) | Phase 4 |
| 4 | JDK Version Inference with Priority Heuristic | Phase 5 |
| 5 | Container Image Resolution | Phase 6 |
| 6 | Transitive Dependency Tree Resolution | Phase 7 |
| 7 | Containerfile Generation from Buildroot Specification | Phase 8 |
| 8 | Gap Detection and Confidence Reporting | Phase 9 |
| 9 | Test Harness and Verification Suite | Phase 1 + Phase 11 |

All 9 core features covered. Nothing deferred beyond spec's existing ## Deferred section.
