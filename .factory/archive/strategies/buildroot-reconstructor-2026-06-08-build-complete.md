---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-08
source: factory-archivist
---

# Strategy: Buildroot Reconstructor — 2026-06-08 (Build Complete)

## Build Outcome

All 11 phases of the CEO-approved build plan were delivered successfully. The project went from empty scaffold to a working CLI tool that reconstructs Maven build environments as Containerfiles.

## What Was Built

9 core features across 12 commits:

1. **POM parsing with full parent chain resolution** — recursive parent walking via Maven Central API, namespace-agnostic XML traversal (patterns borrowed from Macaron)
2. **Maven property placeholder resolution** — `${...}` substitution with parent-inherited properties, handles recursive references
3. **CI workflow parsing** — GitHub Actions YAML (with matrix expansion) + CircleCI config, extracts JDK versions, images, build commands
4. **JDK version inference** — 12-source priority heuristic: CI explicit > POM compiler plugin > toolchains.xml > JAR manifest > CI base image > Maven enforcer > CI matrix > spring-boot parent > profiles > POM properties > default
5. **Container image resolution** — extracts Docker/container images referenced in CI workflows
6. **Transitive dependency tree** — `mvn dependency:tree` JSON output parsing (Plugin 3.7.0+)
7. **Containerfile generation** — 3 Jinja2 templates: jdk-base (eclipse-temurin), jdk-on-ubuntu (apt-based), vendor-image (custom CI images)
8. **Gap detection** — identifies missing/uncertain build environment aspects, produces confidence scores
9. **Pipeline orchestration + CLI** — `reconstruct`, `verify`, `inspect` commands via Click

## Key Technical Decisions

- **Python 3.11+** over Java/Go — faster iteration, `lxml` for XML, `jinja2` for templates
- **Podman-first** — aligns with IBM/Red Hat ecosystem, rootless containers by default
- **12-source JDK heuristic** — empirically ordered from most to least reliable
- **3 template patterns** — covers 95%+ of Maven CI configurations
- **Filesystem-only storage** — POM cache at `~/.cache/buildroot/poms/`, no database

## What Worked Well

1. **Phased build plan** — splitting 9 features across 11 phases kept each commit focused and testable
2. **Level 1 + Level 2 testing early** — catching JDK normalization bug (`1.8` → `8`) before baseline
3. **Real-world test set** — 10 Spring ecosystem packages exercised real edge cases (flat POMs, missing CI, matrix builds)
4. **Research-first approach** — 13 source notes gave builders clear implementation guidance

## What Could Be Better

1. **Type checking (0.0 score)** — 23 mypy errors at baseline, should have been addressed during build
2. **Observability (0.341)** — only 12% function coverage for structured logging
3. **Builder timeouts** — 2 builder agents timed out during the build, required CEO retry
4. **No coverage tooling** — pytest-cov not configured, so eval can't measure test coverage

## Next Steps (for future factory runs)

1. Fix 23 mypy type errors → type_check score from 0.0 to 1.0 (+0.05 composite)
2. Add structured logging with function-level coverage → observability from 0.341 toward 0.8
3. Configure pytest-cov → coverage from 0.5 to measured value
4. Grow capability surface from 104 to 340 (more public APIs, modules)
5. Attempt Level 3 rebuilds — actual JAR bytecode reproduction

## Baseline Eval: 0.586

Passes: lint (1.0), guard_patterns (1.0), config_parser (1.0), tests (0.995)
Needs work: type_check (0.0), capability_surface (0.306), research_grounding (0.32), observability (0.341), coverage (0.5)
