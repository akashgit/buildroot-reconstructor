---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-07
source: factory-archivist
---

# Strategy: Buildroot Reconstructor — 2026-06-07

## Inception Strategy

This is the initial strategy snapshot at project inception. The spec was refined from the research phase with four key changes from the prior draft:

### Strategic Decisions

1. **Podman-first / Containerfile naming**: All output uses `Containerfile` (OCI standard), Podman is the default runtime. Docker/Buildah supported via `--runtime` flag. Surface-level change with no architectural impact.

2. **Transitive deps promoted to core feature**: Originally a non-goal, dependency tree resolution was elevated because supply chain security requires full graph visibility (cf. Log4Shell as transitive dep). Implementation delegates to Maven itself (`mvn dependency:tree`) rather than reimplementing dependency mediation in Python — correct approach given Maven's 20 years of edge-case handling.

3. **GitHub token made optional**: Unauthenticated access (60 req/hr) is the default. Sufficient for the 10-package test set. 403 responses trigger exponential backoff with user-friendly message.

4. **PyGithub removed**: Replaced with direct `requests` calls to GitHub REST API. Eliminates a heavyweight dependency when we only need to fetch files from known paths.

### Architecture Rationale

- **Python over Java/Go**: The research stack is entirely Python (lxml, ruamel.yaml, jinja2). CLI tool with no performance-critical paths — XML parsing and HTTP fetching dominate runtime.
- **`click` over `typer`**: Explicit decorator style suits a tool with multiple distinct commands.
- **Jinja2 over dockerfile-parse for generation**: We're producing Containerfiles, not modifying them. Templates are cleaner for text-with-conditional-blocks.
- **Maven delegation for dep trees**: Do not reimplement Maven's dependency mediation algorithm. It's complex (nearest-definition-wins, scope narrowing, exclusions, optional deps, BOMs) and reimplementing it would be a source of bugs.

### Risk Areas

1. **Property resolution completeness**: The spec explicitly acknowledges incomplete resolution (no settings.xml, no `-D`, no profiles). This is the highest-risk area for inference accuracy.
2. **Composite Action opacity**: Spring projects use `.github/actions/build` composite actions. Only 1 level parsed — if JDK setup is buried deeper, it's missed.
3. **ubuntu-latest drift**: Static lookup table will go stale. Flagged as gap but no auto-update mechanism.

### Verification Strategy (3 tiers)

1. **Structured diff** against known container images (fast, automated)
2. **Cross-reference** against GitHub runner image specs and JAR manifest `Build-Jdk-Spec` (medium, automated)
3. **End-to-end rebuild** via `podman build` + artifact comparison (slow, optional, gated behind `--rebuild` flag)

### Deferred Items (17)

- Level 3 rebuild verification for all 10 test packages
- Deep Gradle parsing, recursive composite action resolution
- Dynamic ubuntu-latest lookup, CircleCI orb resolution
- Private registry auth, per-module Containerfiles
- Profile-activated Maven properties
- GitLab CI / Jenkins / Travis CI support
