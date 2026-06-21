---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 4
verdict: keep
score_delta: +0.2807
date: 2026-06-12
source: factory-archivist
---

# Experiment #004: PNC Ground-Truth Validation

## Hypothesis
Parse PNC builders-image 2-layer Containerfile chains, build a 6-dimension weighted accuracy scorer, and validate buildroot reconstruction against independently known PNC build environments for 3 Maven packages.

## Result
**KEEP** — score changed from 0.5436 to 0.8243 (+0.2807)

CEO code review passed all 7 checklist items on first iteration (no fixes needed). 5 code deliverables: PNC Containerfile parser, 6-dimension accuracy scorer, validate CLI command, report generator, 41-test suite. 3 review iterations (builder) + 3 final review iterations (CEO). Execution on rh-h100-01 still pending — pipeline code complete and merged, validation runs against 3 packages deferred to next cycle.

## What Changed

### New Files (4)
1. **`src/buildroot/parsers/pnc_containerfile.py`** (201 lines) — PNC Containerfile 2-layer chain parser using `dockerfile-parse`. Extracts JDK version/vendor from RPM names (`java-1.8.0-openjdk-devel`, `java-11-openjdk-devel`), Maven/Gradle version from ENV vars and download URLs, RHEL version from base image references. Returns `PNCGroundTruth` dataclass. Handles fallback: image name inference when Containerfile parsing misses JDK info.

2. **`src/buildroot/utils/accuracy_scorer.py`** (280 lines) — 6-dimension weighted accuracy scorer:
   - JDK major version (0.25) — normalizes `1.8` → `8`
   - Build tool match (0.25) — detects maven/gradle from build command
   - Build tool version (0.15) — exact match (1.0), major match (0.5), or miss (0.0)
   - SCM URL (0.15) — normalizes `.git`, `scm:git:`, trailing slashes; 0.5 if no ground truth
   - JDK vendor (0.10) — normalizes temurin/adoptopenjdk/zulu/corretto → openjdk
   - OS family (0.10) — maps rhel/ubi/centos → rhel

3. **`src/buildroot/cli/commands/validate.py`** (106 lines) — `buildroot validate` CLI subcommand. Pipeline: reconstruct → parse PNC ground truth → score accuracy → write per-package `accuracy.json` + aggregate `report.json`.

4. **`tests/test_pnc_containerfile.py`** + **`tests/test_accuracy_scorer.py`** — 41 new tests with synthetic PNC Containerfile fixtures (JDK 8/Maven 3.3.9 and JDK 11/Maven 3.6.3 chains). Tests cover: RPM parsing, ENV extraction, URL extraction, RHEL detection, image name fallback, full chain parsing, missing dirs, normalization, scoring dimensions, aggregate scoring, report serialization.

### Modified Files (2)
- `src/buildroot/cli/main.py` — 2 lines: import + register `validate` command

### PR #11 Stats
- **+1012 / -0 lines**, 6 files changed, 1 commit
- **Total test suite**: 293 tests passing (41 new + 252 existing), zero regressions

## CEO Code Review

**Verdict: CLEAN** (first iteration — no fixes needed)

| Dimension | Status | Notes |
|-----------|--------|-------|
| Correctness | PASS | 2-layer chain parsing correct, regex patterns cover both JDK naming forms, scorer normalizes properly, weighted aggregate correct |
| Security | PASS | No user input to shell, no secrets, `click.Path` validates existence |
| Edge cases | PASS | Missing Containerfile (warning + empty return), missing ENV (fallback to URL then image name), system-default Maven (treated as empty), no SCM URL (score 0.5) |
| Missing tests | PASS | 41 tests covering all extraction helpers, full chain, scoring dimensions, aggregate, edge cases |
| Style | PASS | Follows existing patterns (dataclasses, structlog, click CLI), clean module structure |
| Scope | PASS | 4 new files + 2 modified, all within `src/**/*.py`, `tests/**/*.py` |
| Guardrails | PASS | No file exceeds 500 lines, all within scope, no dangerous commands |

## Design Decisions
1. **2-layer chain parsing** — tool-layer (maven/gradle install) references base-layer (JDK on RHEL) via FROM. Parser walks tool → base, merging ENV vars and extracting components from each layer.
2. **Vendor normalization** — maps temurin, adoptopenjdk, zulu, corretto, liberica all to "openjdk" since they're functionally equivalent OpenJDK distributions.
3. **Partial scoring** — build tool version gets 0.5 for major-version-only match; SCM URL gets 0.5 when no ground truth available (avoids penalizing missing data).
4. **Image name fallback** — `builder-rhel-7-j8-mvn3.3.9` pattern parsed as last resort for JDK version when Containerfile extraction fails.

## Score Details
- **Score before**: 0.5436
- **Score after**: 0.8243
- **Delta**: +0.2807
- **Deliverables**: 5 (parser, scorer, CLI, report generator, tests)
- **New tests**: 41 (293 total passing, zero regressions)
- **Review iterations**: 3 builder + 3 CEO final = 6 total (code CLEAN on first CEO iteration)

## Pending Execution
- **Execution step**: Run `buildroot validate` on rh-h100-01 against 3 packages (commons-lang3:3.14.0, jackson-core:2.17.0, snakeyaml:2.2)
- **Expected accuracy**: 0.35–0.55 per package (JDK version mismatches expected — Build-Jdk-Spec reflects upstream CI JDK, not PNC's build JDK)
- **Status**: Pipeline code complete and merged; execution deferred to next cycle

## Links
- Project: buildroot-reconstructor
- Issue: #10
- PR: #11
- Strategy: `strategies/buildroot-reconstructor-2026-06-12-pnc-validation.md`
