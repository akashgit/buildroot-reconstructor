---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 5
verdict: keep
score_delta: n/a
date: 2026-06-13
source: factory-archivist
type: refinement
refinement_tier: 1
---

# Experiment #005: Execute PNC ground-truth validation on rh-h100-01 for 3 packages

## Hypothesis
Run the PNC ground-truth validation pipeline (implemented in experiment #004) on rh-h100-01 against real PNC builders-image Containerfiles for 3 Maven packages: commons-lang3:3.14.0, jackson-core:2.17.0, snakeyaml:2.2.

## Classification
**Tier 1 — Operational refinement.** No source code changes. Builder SSHed to rh-h100-01, ran existing `buildroot validate` CLI commands, committed generated result files under `results/pnc-validation/`.

## Result
**KEEP** — mean accuracy 0.5833 across 3 packages (range 0.325–0.750). No code changes; result artifacts committed.

## Per-Package Results

| Package | Accuracy | JDK Match | Build Tool | Notes |
|---------|----------|-----------|------------|-------|
| commons-lang3:3.14.0 | 0.325 | MISS (21 vs 8) | Maven ✓ | Build-Jdk-Spec=21 from upstream CI, PNC uses JDK 8. JDK vendor shows unresolved GitHub Actions expression |
| jackson-core:2.17.0 | 0.750 | HIT (8 = 8) | Maven ✓ | Best result. JDK 8 matched PNC, Maven 3.x major version matched, vendor normalized correctly |
| snakeyaml:2.2 | 0.675 | HIT (11 = 11) | Maven ✓ | JDK 11 matched PNC. Maven version extraction missing (empty string in buildroot.json) |

## Key Learnings

1. **Build-Jdk-Spec reports upstream CI's JDK, not PNC's build JDK.** This is the root cause of the commons-lang3 mismatch (spec=21 from GitHub Actions, PNC actually uses JDK 8). The heuristic correctly extracts what's in the manifest, but the manifest itself is misleading for PNC validation purposes.

2. **OS family extraction needs work.** PNC Containerfile parser returns empty string for `os_family` across all 3 packages; scorer marks mismatch vs "unknown" from buildroot. Both sides need improvement.

3. **SCM URL scoring is generous.** When ground truth SCM is empty, scorer gives 0.5 (partial credit). Acceptable design choice but inflates scores for packages where PNC Containerfiles don't encode SCM info.

4. **Maven version extraction gap.** snakeyaml's buildroot.json has empty string for Maven version despite the PNC image name encoding `mvn3.6.3`. The `buildroot reconstruct` pipeline doesn't extract Maven version from all available sources.

5. **JDK vendor field unreliable.** commons-lang3 shows an unresolved GitHub Actions expression (`${{ ... }}`) in the JDK vendor field — the parser extracted it literally from CI config.

## What Changed
- Commit c378994: `results: PNC ground-truth validation for 3 packages on rh-h100-01`
- Files added: `results/pnc-validation/report.json`, per-package `accuracy.json`, `buildroot.json`, `Containerfile` for all 3 packages
- No source code modifications

## Decision Rationale
KEEP because:
1. Pipeline executed successfully — validates that experiment #004's code works against real PNC infrastructure
2. Results provide actionable signal for improving reconstruction accuracy (JDK spec vs actual, OS family, Maven version)
3. jackson-core at 0.750 demonstrates the pipeline works well when JDK versions align
4. The 0.5833 mean establishes a quantitative baseline for future improvement experiments

## CEO Code Review
**CLEAN** — execution-only refinement, no source code modified. All result files verified: valid JSON, 3 packages present, correct directory structure. All 7 checklist items PASS.

## Improvement Opportunities Identified
1. Add PNC-specific JDK resolution: parse image name `builder-rhel-7-j{JDK}` as authoritative JDK source
2. Implement OS family extraction from PNC Containerfile `FROM` base image
3. Fix Maven version extraction pipeline to cover all sources (POM properties, wrapper config, CI config)
4. Consider demoting Build-Jdk-Spec priority when PNC ground truth is available

## Links
- Project: buildroot-reconstructor
- Parent experiment: #004 (PNC ground-truth validation pipeline)
- Commit: c378994
- Branch: factory/run-9a7c8d56
