---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 002
verdict: KEEP
score_delta: n/a
date: 2026-06-08
source: factory-archivist
---

# Experiment #002: Level 3 build verification refinement — 10/10 builds passing

## Hypothesis
Refine Level 3 full rebuild for all 10 test packages — fix JDK inference, Gradle build support, template generation, and build command detection to achieve 100% build pass rate.

## Context
After experiment #001 established the 6 Level 3 gap fixes in code, actual end-to-end container builds were only passing for 3/10 packages. This refinement experiment targeted the remaining 7 build failures through iterative debugging on real hardware.

## Builder Implementation

**Branch**: `factory/run-d6d6f670`
**Files changed**: 14 (+745 / -61 lines)
**Commits**: 4 (fbc12db → 4f61ea7)

### Fix 1 — Gradle CI Task Fallback and Multi-Module Path
**Commit**: fbc12db
- Gradle builds now fall back to `build` task when CI-specific tasks (e.g., `check`) are not found
- Multi-module `module_path` correctly resolved for nested Gradle subprojects
- JDK matrix `min-version` inference improved for CI workflows with version matrices

### Fix 2 — Gradle --no-daemon, Module-Path Build Commands, Build Tool Detection
**Commit**: d75f65c
- Added `--no-daemon` flag to all Gradle invocations (avoids daemon issues in containers)
- Module-path build commands correctly generated for multi-module projects
- Build tool detection improved to distinguish Maven vs Gradle from CI workflow steps
- JDK min-version selection fixed for matrix builds

### Fix 3 — GRADLE_OPTS in Containerfile Templates
**Commit**: 7ed2b3e
- All 3 Jinja2 templates now use `ENV GRADLE_OPTS` for memory configuration
- Replaced inline `-Xmx` flags with proper environment variable approach
- Templates: `custom_base.j2`, `jdk_base.j2`, `jdk_on_ubuntu.j2`

### Fix 4 — Created-By JDK from Manifest, Nested module_path Detection
**Commit**: 4f61ea7
- `fetch_jar_manifest_jdk()` now parses `Created-By` header (e.g., `Created-By: 21.0.1 (Eclipse Adoptium)`)
- Falls back to `Created-By` when `Build-Jdk-Spec` is absent
- Nested `module_path` detection for multi-module projects with non-root build paths
- `maven_central.py` updated with `_parse_created_by_jdk()` utility

### Tests
- **438+ lines** added to `tests/test_level3_fixes.py`
- Gradle-specific tests: CI task fallback, module-path resolution, --no-daemon flag
- Created-By JDK parsing tests
- Multi-module path detection tests
- Integration tests for all 10 packages

## Build Verification
**Environment**: rh-h100-01 (160 cores, 1.7TB RAM)
**Runtime**: Podman
**Packages verified**:
1. spring-core — PASS
2. spring-context — PASS
3. spring-boot — PASS
4. spring-cloud-config-client — PASS
5. spring-data-commons — PASS
6. commons-lang3 — PASS
7. micrometer-core — PASS
8. thymeleaf-spring5 — PASS
9. spring-security-core — PASS
10. spring-boot-starter-web — PASS

**Before**: 3/10 builds passing
**After**: 10/10 builds passing (100%)

## Result
**KEEP** — Level 3 build pass rate improved from 30% to 100%.

## What Changed
4 commits fixing Gradle build support (--no-daemon, GRADLE_OPTS, task fallback), JDK inference from Created-By manifest header, multi-module path detection, and build tool detection heuristics. All 10 Spring ecosystem test packages now build successfully in containers on rh-h100-01.

## Decision Rationale — KEEP
1. Build pass rate went from 3/10 (30%) to 10/10 (100%)
2. All changes are incremental refinements on experiment #001's infrastructure
3. Gradle support significantly improved (was the primary blocker for 5+ packages)
4. JDK inference now covers both Build-Jdk-Spec and Created-By manifest headers
5. Builds verified on real hardware (rh-h100-01, 160 cores, 1.7TB RAM)

## Key Lessons
- **Gradle needs special treatment in containers**: `--no-daemon` is essential, `GRADLE_OPTS` via ENV is cleaner than inline flags
- **Created-By header is a reliable JDK signal**: When Build-Jdk-Spec is absent, Created-By provides the actual build JDK version
- **Multi-module path detection is subtle**: Nested modules don't always follow the artifact-id convention for directory names
- **Real hardware testing is non-negotiable for build verification**: Inference logic that looks correct locally can fail in actual container builds

## Links
- Project: buildroot-reconstructor
- Branch: factory/run-d6d6f670
- Commits: fbc12db, d75f65c, 7ed2b3e, 4f61ea7
- Prior experiment: experiments/buildroot-reconstructor-001.md
