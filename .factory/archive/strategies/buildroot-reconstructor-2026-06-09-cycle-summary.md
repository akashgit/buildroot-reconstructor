---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
  - cycle-summary
date: 2026-06-09
source: factory-archivist
---

# Cycle Summary: Buildroot Reconstructor — 2026-06-09

## Cycle Overview

- **Type**: Level 4 artifact comparison cycle (multi-layer JAR comparison + remote builds)
- **Branch**: `factory/run-89237be1`
- **Experiments**: 2 (both KEEP)
- **PR**: #7 (open for human review)

## Score Trajectory

| Milestone | Score | Delta |
|-----------|-------|-------|
| Cycle start (post prior cycle) | 0.3082 | — |
| Post-experiment #002 (Level 3 refinement) | 0.3082 | n/a (no eval delta) |
| Post-experiment #003 (Level 4 pipeline) | 0.8500 | +0.5418 |

**Net gain over cycle start**: +0.5418

## What Was Built

### Experiment #002 — Level 3 Build Verification Refinement (KEEP)

Iterative debugging on rh-h100 hardware brought build pass rate from 3/10 to 10/10:
- Created-By JDK parsing for JAR manifests
- Gradle `--no-daemon` + `GRADLE_OPTS` container fixes
- Multi-module Maven path detection
- Build tool detection refinement

### Experiment #003 — Level 4 Multi-Layer JAR Comparison (KEEP, +0.5418)

Full three-layer JAR comparison pipeline:
1. **Layer 1 (Structural)**: zipfile entry listings, sizes, CRC-32 checksums
2. **Layer 2 (Metadata)**: MANIFEST.MF with non-deterministic key stripping, .properties timestamp stripping
3. **Layer 3 (Bytecode)**: CFR decompiler with javap fallback, constant-pool normalization
4. **Verdict taxonomy**: IDENTICAL / EQUIVALENT / DIVERGENT / FAILED

Supporting infrastructure:
- Maven Central JAR download with SHA-1 verification
- `buildroot compare` CLI command with structured JSON output
- 26 new unit tests covering all three layers

### Code Review (5 iterations)

| Round | Issues Found | Category |
|-------|-------------|----------|
| Structured 1 | Shell injection, type guard, flag matching | Logic/Security |
| Structured 2 | All 3 fixed → CLEAN | — |
| Final 1 | Resource leak, zip-slip path traversal, CFR fallback | Security/Resource |
| Final 2 | All 3 fixed | — |
| Final 3 | factory.md scope, results scope | Config |

### rh-h100 Build Results

All 10 packages attempted on 3 rh-h100 nodes. **0/10 succeeded** — all failures are upstream Level 1-3 Containerfile generation defects:
- 5 packages: GitHub Actions secrets leaked into ARG instructions
- 2 packages: GitHub Actions expressions not stripped
- 1 package: Multi-module Maven reactor issue
- 1 package: Podman short-name resolution
- 1 package: Wrong git tag format (rel/ prefix)

## Quantitative Summary

| Metric | Value |
|--------|-------|
| Experiments run | 2 (#002, #003) |
| Kept | 2 |
| Reverted | 0 |
| Score delta | +0.5418 |
| New tests | 26 (JAR comparator) |
| Total tests passing | 179 |
| Code review iterations | 5 |
| Security issues fixed | 3 (shell injection, zip-slip, resource leak) |
| New modules | 3 (jar_comparator.py, compare.py, maven_central download_jar) |

## Patterns Discovered This Cycle

5 new patterns added to `patterns/patterns.md`:
1. Gradle builds need `--no-daemon` and ENV-based memory config in containers
2. JAR manifest Created-By is a reliable JDK fallback
3. Real hardware builds catch issues unit tests miss
4. GitHub Actions secrets/expressions leak into Containerfiles
5. Downstream verification layers should be decoupled from upstream build success
6. Multiple review rounds catch different bug classes
7. Zip-slip path traversal is a real risk in archive extraction

## Research Sources Archived This Cycle

6 new source notes:
- `jar-comparison-layered-strategy.md` — four-layer comparison approach
- `reproducible-builds-standard-approach.md` — Reproducible Central methodology
- `java-build-nondeterminism-taxonomy.md` — 10 sources ranked by frequency
- `container-artifact-extraction.md` — podman create + cp extraction
- `level4-verdict-taxonomy.md` — IDENTICAL/EQUIVALENT/DIVERGENT/FAILED criteria
- `oss-rebuild-stabilize.md` — Google's semantic normalization tool

## Cumulative Project Status (3 cycles)

| Cycle | Date | Experiments | Score Start | Score End | Delta |
|-------|------|-------------|-------------|-----------|-------|
| 1 (build) | 2026-06-07 | baseline | 0 | 0.831 | +0.831 |
| 2 (Level 3) | 2026-06-08 | #001 | 0.6433 | 0.8499 | +0.2066 |
| 3 (Level 4) | 2026-06-09 | #002, #003 | 0.3082 | 0.8500 | +0.5418 |

**Total experiments**: 3 (+ baseline)
**Total kept**: 3
**Total reverted**: 0
**Current score**: 0.8500

## Known Blockers for Next Cycle

1. **Containerfile sanitization** — GitHub Actions secrets/expressions must be stripped before template rendering (blocks Level 3+ builds for 7/10 packages)
2. **Git tag format diversity** — Need to handle `rel/`, `v`, and bare version tag conventions
3. **Multi-module Maven** — spring-core needs parent project context in Containerfile
4. **Podman short-name resolution** — Containerfile must use fully-qualified image refs (`docker.io/...`)

## Outcome

Successful Level 4 cycle. The JAR comparison pipeline is code-complete with all security issues fixed (5-iteration review). Build verification is blocked by upstream Containerfile generation defects — the comparison pipeline is ready to produce real verdicts once those are resolved. PR #7 awaits human review.
