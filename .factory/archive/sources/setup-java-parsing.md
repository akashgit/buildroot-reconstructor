---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
---

# GitHub Actions `setup-java` Parsing — Three Matrix Patterns

## Finding

The `actions/setup-java` action (stable across v3/v4/v5) exposes `java-version`, `distribution`, `java-package`, and `java-version-file`. Three matrix patterns exist in the wild.

## Matrix Patterns

1. **Direct value**: `java-version: '17'` — trivial extraction
2. **Matrix variable**: `java-version: ${{ matrix.java-version }}` — resolve from `strategy.matrix.java-version`
3. **Nested matrix object** (Spring Boot pattern): `java-version: ${{ matrix.java.version }}` — resolve from `strategy.matrix.java[*].version`

## Spring Boot Complication

Spring Boot's CI uses composite actions with multi-level indirection:
- `.github/workflows/ci.yml` → `.github/actions/build` (composite) → `.github/actions/prepare-gradle-build` (composite) → `actions/setup-java@v5`

The `java-version` input is threaded through each composite action level.

## V1 Extraction Algorithm

1. Parse all jobs, find steps matching `uses: actions/setup-java@*`
2. Extract `with.java-version` and `with.distribution`
3. If value contains `${{ matrix.* }}`, resolve against `strategy.matrix`
4. If value contains `${{ inputs.* }}`, fetch composite `action.yml` one level deep
5. Handle `exclude` blocks by noting gaps (don't evaluate expressions in v1)

## Multi-Line java-version

`setup-java` accepts newline-separated versions for multi-JDK installs. Split on `\n`, take first non-empty line as primary version.

## V1 Simplification

Support patterns 1 and 2 fully. Pattern 3 (composite actions): fetch one level deep, log a gap if unresolvable.
