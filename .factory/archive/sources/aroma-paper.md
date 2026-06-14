---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-08
---

# AROMA — Automatic Reproduction of Maven Artifacts (ACM 2024)

## Summary

AROMA heuristically recovers source repos, JDK versions, and build commands from POM metadata and published artifacts. Published at ACM 2024 (doi: 10.1145/3643764).

## Relevance to Buildroot Reconstructor

AROMA addresses the same problem space — reconstructing build environments from artifact metadata. Key techniques applicable to our Level 3 work:

1. **Source repo detection** from POM SCM fields (same gap we identified)
2. **JDK version inference** from multiple signals including JAR manifest
3. **Build command recovery** from POM plugin analysis

## Key Differentiator

AROMA focuses on bytecode-level reproduction verification. Buildroot Reconstructor focuses on producing a Containerfile (environment specification) rather than just build commands.

## Reference

[AROMA: Automatic Reproduction of Maven Artifacts](https://dl.acm.org/doi/10.1145/3643764)
