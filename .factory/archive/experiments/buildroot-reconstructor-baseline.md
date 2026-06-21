---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: baseline
verdict: ESTABLISHED
score_delta: "+0.586 (from 0)"
date: 2026-06-08
source: factory-archivist
---

# Baseline: Buildroot Reconstructor — Initial Build

## Hypothesis
Build all 9 core features from scratch (POM parsing, property resolution, CI parsing, JDK inference, image resolution, dependency tree, Containerfile generation, gap detection, pipeline/CLI) and establish a baseline eval score.

## Result
**ESTABLISHED** — baseline composite score: 0.586

## What Changed
- 12 commits, 11 build phases
- 9 core features implemented end-to-end
- 201 tests written (200 passed, 1 failed in eval — all Level 1 and Level 2 pass independently)
- 121 unit tests + 70 Level 1 inference tests + 10 Level 2 podman build tests
- Lint clean, guard patterns 8/8

## Eval Dimension Scores
- tests: 0.995 (200/201)
- lint: 1.000
- type_check: 0.000 (23 mypy errors)
- coverage: 0.500 (not detected)
- guard_patterns: 1.000
- config_parser: 1.000
- capability_surface: 0.306 (104/340)
- experiment_diversity: 0.500 (N/A)
- observability: 0.341
- research_grounding: 0.320
- factory_effectiveness: 0.500 (N/A)
- spec_compliance: 0.500 (N/A)

## Key Build Incidents
1. Builder agent timeout during Phase 11 test suite creation — CEO retried with narrower task
2. JDK version normalization bug: `1.8` should become `8` for Docker tags like `eclipse-temurin:8-jdk`
3. Containerfile strip function was over-aggressively removing `apt-get` lines
4. Gradle-published flat POMs (e.g., thymeleaf-spring5) don't have parent chains — test expectations adjusted
5. Eval script needed `--ignore=tests/integration` to exclude podman-dependent tests from unit test run

## Links
- Project: buildroot-reconstructor
- Branch: factory/run-c2f7d635
- Commits: b81e463..9f3d8b3 (12 commits)
