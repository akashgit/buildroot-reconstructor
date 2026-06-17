---
tags:
  - factory
  - source
  - reproducibility
source: factory-archivist
date: 2026-06-16
---

# Reproducible Build Maven Plugin

**Tool**: [zlika/reproducible-build-maven-plugin](https://zlika.github.io/reproducible-build-maven-plugin/)

## What It Does

Strips non-deterministic data from JAR archives during the build:
- ZIP timestamps
- MANIFEST.MF ordering
- pom.properties timestamps

This is a **build-time** solution (add to Maven command) rather than post-build canonicalization.

## Complementary Tools

- [Apache Maven Reproducible Builds Guide](https://maven.apache.org/guides/mini/guide-reproducible-builds.html) — recommends `<project.build.outputTimestamp>` in POM
- [Maven Artifact Plugin](https://maven.apache.org/plugins/maven-artifact-plugin/reproducible.html) — diagnoses reproducibility issues
- [Chains-Rebuild](https://github.com/chains-project/reproducible-central) — post-build canonicalization

## Relevance

For issue #27 P6 (reproducible build flags), the primary fix is adding `-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z` to Maven commands. This plugin is a stronger alternative for projects that can modify their POM, but since buildroot reconstructs builds without modifying source, the command-line flag + post-build MANIFEST.MF stripping is the correct approach.
