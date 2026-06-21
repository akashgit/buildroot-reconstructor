---
tags:
  - factory
  - source
source: factory-archivist
date: 2026-06-07
---

# Reproducible Central

## Key Findings

- Maintains hand-written `.buildspec` files for Maven Central artifacts (~800 projects)
- Each buildspec captures: source repo URL, git tag, JDK version, Maven version, build command, expected artifacts with checksums
- 88.6% shell scripts — uses `rebuild.sh` to execute builds in Docker containers
- Buildspec format is the de facto standard for Maven build environment metadata
- Our `buildroot.json` sidecar is designed for interoperability with this format

## Relevance

- Provides the validation baseline — our generated Containerfiles should be consistent with their hand-written buildspecs where available
- Their format informs our `buildroot.json` schema
- Producer-side (manual) approach vs. our consumer-side (automated) approach

## Reference

- Repository: https://github.com/jvm-repo-rebuild/reproducible-central
