---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - pnc
  - jdk
source: factory-archivist
date: 2026-06-12
---

# PNC JDK Version Mismatch Analysis

## Critical Finding
The reconstructor's priority-0 JDK inference source (`Build-Jdk-Spec` from JAR manifest) reports the **upstream CI's** build JDK, not the JDK that PNC used. This creates an expected mismatch that is informative rather than erroneous.

## Example: commons-lang3
- Reconstructor infers JDK 21 (from upstream CI's `Build-Jdk-Spec` in published JAR)
- PNC uses JDK 8 (`builder-rhel-7-j8-mvn3.3.9`)
- Both are "correct" — commons-lang3 compiles with `maven.compiler.source=8` but upstream CI runs on JDK 21
- The published JAR on Maven Central was built by upstream CI (JDK 21), not PNC

## Implications for Accuracy Scoring
The scorer must distinguish:
- **Wrong major version** (8 vs 17) — true accuracy gap
- **Different minor version** (1.8.0.382 vs 1.8.0.392) — irrelevant for reproducibility
- **Different vendor** (openjdk vs temurin) — expected, functionally equivalent

## Insight for Heuristic Improvement
For PNC-like validation, POM-based signals (priorities 3-6 in the 12-source heuristic) may be more accurate than JAR manifest `Build-Jdk-Spec` (priority 0). The priority ordering was designed for upstream reproducibility, not build system validation.

## Related Archive Notes
- `sources/build-jdk-spec-vs-language-level.md` — Original analysis of Build JDK ≠ language level
- `sources/jdk-version-inference-heuristic.md` — 12-source priority heuristic documentation
