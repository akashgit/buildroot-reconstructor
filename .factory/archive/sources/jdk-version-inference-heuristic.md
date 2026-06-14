---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
---

# JDK Version Inference — Priority Heuristic

## Finding

JDK version can appear in 12+ locations. A strict priority order is needed to pick the right one. CI workflow sources take priority over POM sources because `maven.compiler.source` specifies the **language level** (minimum), not the **actual JDK used**.

## Priority Order (highest first)

1. CI workflow: `setup-java` action `java-version`
2. CI workflow: `JAVA_HOME` env var (e.g., `JAVA_HOME_17_X64`)
3. POM property: `<maven.compiler.release>`
4. POM property: `<maven.compiler.source>`
5. POM property: `<maven.compiler.target>`
6. POM plugin config: `maven-compiler-plugin` `<release>`
7. POM plugin config: `maven-compiler-plugin` `<source>`
8. Spring Boot POM: `<java.version>`
9. Maven Enforcer: `requireJavaVersion`
10. `.java-version` file in repo root
11. `.sdkmanrc` file in repo root
12. `.tool-versions` (asdf) in repo root
13. Default: JDK 17

## Critical Distinction

Source level 11 can compile on JDK 17. For buildroot reconstruction, we want the **actual JDK used in CI**, not the minimum language level. This is why CI workflow analysis must take priority over POM analysis.

## GitHub Runner Pre-installed JDKs

Ubuntu 24.04 runner ships with Adoptium Temurin 8, 11, 17, 21 via `JAVA_HOME_*` env vars.

## `ubuntu-latest` Moving Target

| Period | Maps to |
|--------|---------|
| Before Dec 2024 | Ubuntu 22.04 |
| Dec 2024 – Jan 2025 | Rolling migration |
| After Jan 2025 | Ubuntu 24.04 |

Strategy: maintain a lookup table mapping `runs-on` values to base images and pre-installed tools. For `ubuntu-latest`, use configurable default with a warning.
