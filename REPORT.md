# Buildroot Reconstructor — Level 3 Verification Report

**Date:** 2026-06-09
**Project:** Buildroot Reconstructor
**Result:** 10/10 test packages build from source inside reconstructed containers

---

## What We Built

An AI-driven pipeline that reconstructs **buildroots** — complete, isolated build environments — from a Java package's public metadata alone. Given only a Maven coordinate (groupId, artifactId, version), the system:

1. Fetches and parses the POM XML (dependency tree, parent chain, properties, plugins, SCM metadata)
2. Discovers the source repository and correct git tag via GitHub API
3. Fetches and parses CI workflows (GitHub Actions, CircleCI) for environment signals
4. Infers the JDK version from multiple sources (JAR manifest, CI matrix, POM properties)
5. Detects the build tool (Maven vs Gradle), version, and wrapper configuration
6. Generates a Containerfile that clones the source, installs the right toolchain, and runs the build

## Three Levels of Verification

The system uses a three-tier verification strategy, each level building on the previous:

### Level 1 — Metadata Correctness

**What:** Validate that the pipeline correctly extracts and resolves metadata from Maven Central POMs.

**How we verify:**
- Parse the POM XML and resolve property placeholders (`${spring.version}` → `5.3.18`)
- Walk the parent POM chain to inherit groupId, version, properties, and plugin management
- Extract SCM coordinates, project URL, and build plugin configuration
- Assert extracted values match expected ground truth for each test package

**Coverage:** 154 test assertions across POM parsing, property resolution, parent inheritance, plugin detection, and SCM extraction.

### Level 2 — Containerfile Generation

**What:** Validate that the generated Containerfile is syntactically correct and structurally sound — right base image, right JDK, right build commands.

**How we verify:**
- Generate a Containerfile for each test package
- Parse the Containerfile content to verify:
  - Base image matches the inferred JDK version (e.g., `eclipse-temurin:8-jdk` for Spring Framework 5.3.x)
  - Build tool installation matches the detected tool and version
  - Build commands include correct flags (`-DskipTests`, `-Dgpg.skip=true`, `--no-daemon` for Gradle)
  - Source acquisition uses `git clone` with the discovered tag (not `COPY . .`)
  - For multi-module projects, the build targets the correct submodule
- Run `podman build --no-cache` to verify the Containerfile is syntactically valid and the image builds

**Coverage:** 10 parametrized test cases, one per package. Each generates a real Containerfile and attempts a `podman build`.

### Level 3 — Full Source Rebuild

**What:** The definitive test. Clone the actual source code at the correct tag inside the reconstructed container and build the artifact from source. If the build succeeds, the reconstructed buildroot is functionally correct.

**How we verify:**
- `podman build --no-cache` using the generated Containerfile
- The Containerfile:
  1. Starts from the correct base image (e.g., `eclipse-temurin:8-jdk` on Ubuntu)
  2. Installs the build tool (Maven or Gradle) at the detected version
  3. Clones the source repo at the discovered git tag (`git clone --depth 1 --branch <tag>`)
  4. Sets the working directory to the correct module path (for monorepos)
  5. Runs the build command with all enriched flags
- Build exit code 0 = the reconstructed environment is sufficient to build the artifact from source
- Container output is captured for debugging on failure

**Coverage:** All 10 test packages verified on real hardware (rh-h100-01: 160 cores, 1.7TB RAM, podman runtime).

## Test Packages and Results

| # | Package | Version | Build Tool | JDK | JDK Source | Build Time | Machine |
|---|---------|---------|-----------|-----|------------|-----------|---------|
| 1 | commons-lang3 | 3.14.0 | Maven | 21 | JAR manifest `Build-Jdk-Spec` | ~2 min | Local Mac |
| 2 | micrometer-core | 1.10.13 | Gradle | 11 | CI `setup-java` | ~3 min | Local Mac |
| 3 | thymeleaf-spring5 | 3.0.15.RELEASE | Maven | 11 | JAR manifest `Build-Jdk-Spec` | ~2 min | Local Mac |
| 4 | spring-data-jpa | 2.7.18 | Maven | 17 | CI `setup-java` | ~5 min | Local Mac |
| 5 | spring-cloud-config-server | 3.1.8 | Maven | 17 | CI `setup-java` | ~4 min | Local Mac |
| 6 | spring-boot-starter-web | 2.7.18 | Gradle | 17 | CI `setup-java` | ~1 min | Local Mac |
| 7 | spring-security-core | 5.8.9 | Maven | 17 | CI `setup-java` | ~8 min | Local Mac |
| 8 | spring-core | 5.3.31 | Gradle | 8 | JAR manifest `Created-By` | ~25 min | rh-h100-01 |
| 9 | spring-context | 5.3.31 | Gradle | 8 | JAR manifest `Created-By` | ~25 min | rh-h100-01 |
| 10 | spring-boot | 2.7.18 | Gradle | 17 | CI `setup-java` | ~40 min | rh-h100-01 |

**All 10 pass.** Three packages (spring-core, spring-context, spring-boot) required H100 hardware due to large monorepo Gradle builds exceeding local Mac memory limits.

## Six Gaps Fixed

The initial implementation (Level 1+2) could generate Containerfiles but they failed Level 3 because of six missing capabilities:

### Gap 1 — Dead SCM Extraction

**Problem:** The POM parser had a `<scm>` extraction path that was never wired up — the loop body was `pass`. Source repos couldn't be discovered from POM metadata.

**Fix:** Full SCM parsing: `<connection>`, `<developerConnection>`, `<url>`, `<tag>` elements. URL normalization for `scm:git:`, `git://`, `git@` prefixes. Gitbox Apache support. Fallback chain through multiple SCM fields, maven-scm-plugin config, and project URL.

### Gap 2 — Hardcoded Git Tags

**Problem:** Tags were hardcoded as `v{version}`, but real projects use many formats: `thymeleaf-3.0.15.RELEASE`, `commons-lang-3.14.0`, bare `3.14.0`.

**Fix:** GitHub API tag discovery with pagination. Tries `v{version}`, `{artifactId}-{version}`, `rel/{artifactId}-{version}`, bare `{version}`, then fuzzy suffix matching as fallback.

### Gap 3 — COPY-Based Templates

**Problem:** Containerfile templates used `COPY . .` to get source code into the container, which requires the source to be present at build time. In CI this works; in reconstruction it doesn't.

**Fix:** Templates now conditionally emit `git clone --depth 1 --branch <tag> <repo> /build` when source repo and tag are known. Falls back to `COPY . .` when they aren't.

### Gap 4 — Wrong JDK (Language Level vs Build JDK)

**Problem:** JDK version was inferred from CI `setup-java` or POM `<maven.compiler.source>`, which gives the *language level* (e.g., Java 8 source compatibility) not the *build JDK* (e.g., built with JDK 21). Spring Framework 5.3.x is Java 8 compatible but built with JDK 8.

**Fix:** Added Priority 0 JDK signal: download the published JAR from Maven Central, read `META-INF/MANIFEST.MF`, extract `Build-Jdk-Spec` (preferred) or `Created-By` (fallback). The `Created-By: 1.8.0_372 (Oracle Corporation)` header correctly maps to JDK 8. This is the most authoritative signal — it comes from the actual build that produced the artifact.

### Gap 5 — Missing Build Flags

**Problem:** Build commands lacked critical flags: GPG signing failed without keys (`-Dgpg.skip=true`), Apache RAT license checks blocked builds (`-Drat.skip=true`), test execution was attempted (`-DskipTests`).

**Fix:** Build command enrichment: detects `maven-gpg-plugin` → adds `-Dgpg.skip=true`, detects `apache-rat-plugin` → adds `-Drat.skip=true`, always adds `-DskipTests`, detects Maven wrapper → uses `./mvnw`.

### Gap 6 — Gradle Support

**Problem:** Gradle builds failed for multiple reasons: daemon conflicts in containers, OOM with default heap, wrong task names, no module-scoped builds for monorepos.

**Fix:** `--no-daemon` flag for all Gradle invocations, `ENV GRADLE_OPTS="-Xmx4g"` in templates, task fallback from CI-specific tasks to generic `build`, module-path detection for monorepo builds (`:spring-boot-project:spring-boot:build` syntax).

## JDK Inference Priority Stack

The system uses a four-level priority stack to determine the correct JDK version:

| Priority | Source | Confidence | Example |
|----------|--------|-----------|---------|
| P0 | JAR manifest `Build-Jdk-Spec` | OBSERVED | `Build-Jdk-Spec: 21` → JDK 21 |
| P0 | JAR manifest `Created-By` | OBSERVED | `Created-By: 1.8.0_372` → JDK 8 |
| P1 | CI workflow `setup-java` | INFERRED | `java-version: '17'` → JDK 17 |
| P2 | CI workflow matrix minimum | INFERRED | `matrix: [11, 17, 21]` → JDK 11 |
| P3 | POM `maven.compiler.source` | INFERRED | `<source>1.8</source>` → JDK 8 |
| P4 | Default | DEFAULT | JDK 17 |

P0 (JAR manifest) is the most authoritative because it comes from the actual published artifact. This resolved the spring-core/spring-context builds — CI shows JDK 17 for new branches, but the 5.3.x JARs were built with JDK 8.

## Architecture

```
Maven Central                    GitHub API
    │                                │
    ├── POM XML ──┐                  ├── CI Workflows ──┐
    │             │                  │                   │
    └── JAR ──┐   │                  ├── Git Tags ──┐   │
              │   │                  │              │   │
              ▼   ▼                  ▼              ▼   ▼
         ┌─────────────────────────────────────────────────┐
         │              Orchestrator Pipeline               │
         │                                                  │
         │  POM Parser → SCM Discovery → Tag Discovery →   │
         │  CI Parser → JDK Resolver → Build Enrichment →  │
         │  Containerfile Generator (Jinja2 templates)      │
         └──────────────────────┬───────────────────────────┘
                                │
                                ▼
                         Containerfile
                                │
                                ▼
                    podman build --no-cache
                                │
                                ▼
                     Built artifact (JAR)
```

## Test Coverage

| Test File | Tests | What It Covers |
|-----------|-------|---------------|
| `tests/test_level3_fixes.py` | 34 | All 6 gap fixes: SCM parsing, URL normalization, tag discovery, template git clone, JDK from manifest, build enrichment, Maven wrapper, Created-By parsing, full pipeline integration |
| `tests/test_containerfile.py` | 10 | Level 2: Containerfile generation correctness per package |
| `tests/test_level2.py` | 10 | Level 2+3: Full podman build per package |
| Other test files | ~100+ | Level 1: POM parsing, property resolution, parent chain, plugin detection |

Total: 154+ automated tests.

## What's Next (Backlog)

- **Artifact comparison:** After building from source, compare the output JAR byte-for-byte (or class-for-class) against the Maven Central artifact to verify reproducibility
- **Deep Gradle parsing:** Parse `build.gradle` / `settings.gradle` for accurate task/plugin detection instead of relying on CI workflow signals
- **Per-module Containerfiles:** Generate separate Containerfiles for each module in a multi-module project instead of building the entire monorepo
- **More CI systems:** GitLab CI, Jenkins, Travis CI workflow parsing
- **CircleCI orb resolution:** Resolve environment from CircleCI orbs
- **Private registries:** Support ECR, GCR, Artifactory authentication for container base images
- **Beyond Maven:** Extend to Gradle-native, npm, pip package ecosystems
