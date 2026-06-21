---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-08
source: factory-archivist
---

# Strategy: Buildroot Reconstructor — 2026-06-08 (Level 3 Gaps)

## Context

First factory improvement cycle after build completion. Composite score at 0.831 (tests 1.0, lint 1.0, type_check 0.4, coverage 1.0, observability 0.091). Project has strong Level 1/2 infrastructure (121 tests, 80% coverage, all passing) but has never executed a Level 3 source rebuild.

## CEO Verdict

**PROCEED** — Plan approved without issues. All 6 gaps bundled into one hypothesis as interdependent fixes. Builder instructed to implement in order: SCM → tags → templates → JDK → build command → Maven wrapper.

## Design Space Assessment

| Dimension | Score | Notes |
|---|---|---|
| Features | 3 | Core pipeline exists, Level 1/2 pass 80/80 |
| Bug fixes | 1 | SCM extraction dead code, JDK inference wrong for non-Spring |
| Instrumentation | 1 | 12% function coverage, no tracing, observability 0.091 |
| Operational execution | 0 | Level 3 builds never run end-to-end |

**Underserved:** Operational execution, Bug fixes, Instrumentation

## Approved Hypothesis

### H1: Fix all 6 Level 3 gaps and run full source rebuilds for 10 test packages
- **Category:** FIX (mixed)
- **Growth dimension:** capability_surface
- **Priority:** high

Six interdependent fixes bundled into one PR:

1. **SCM extraction from POM XML** — Implement real parsing in `discover_repo_from_pom()` (currently dead code). Parse `<scm>` elements, normalize URLs, handle Apache gitbox→github mapping.
2. **Git tag format discovery** — Replace hardcoded `v{version}` with dynamic tag detection via GitHub API. Support patterns: `v{version}`, `{artifactId}-{version}`, `rel/{artifactId}-{version}`, bare `{version}`.
3. **Template source acquisition** — Replace `COPY . .` with `git clone` block in all 3 Jinja2 templates. Keep `COPY . .` as fallback when `source_repo` is empty.
4. **JDK from JAR manifest** — Add Priority 0 signal: download JAR, read `Build-Jdk-Spec` from `MANIFEST.MF`. Overrides `maven.compiler.source`. Fixes commons-lang3 (needs 21, gets 8).
5. **Build command enrichment** — Detect GPG/RAT plugins → append skip flags. Detect Maven Wrapper → use `./mvnw`. Always add `-DskipTests`.
6. **Maven version from wrapper** — Check `.mvn/wrapper/maven-wrapper.properties` via GitHub API. Extract exact Maven version from `distributionUrl`.

**Expected impact:** capability_surface 0.0 → 0.5+ (Level 3 builds generating correct Containerfiles for majority of test packages)

## Research Grounding

- BuildGen (arXiv:2509.08204), AROMA (ACM 2024), and Reproducible Central all confirm the priority ordering
- 84% of top Maven artifacts lack CI — POM/manifest fallback is the common path
- CEO confirmed: all 6 should be bundled, Maven wrapper (Priority 6) can be deferred only if scope is too large

## Anti-patterns Identified

- Don't fix SCM without tag discovery (commons-lang3 uses `rel/commons-lang-3.14.0`, not `v3.14.0`)
- Don't use `COPY . .` for Level 3 — must clone from source repo
- Don't trust `maven.compiler.source` as build JDK — cross-compilation is common
- Don't hardcode tag formats — discover dynamically via GitHub API
- Don't omit `-Dgpg.skip` and `-Drat.skip` — will fail without keys/configs
- Don't implement fixes in isolation — all 6 are interdependent
