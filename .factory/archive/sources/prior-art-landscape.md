---
tags:
  - factory
  - source
source: factory-archivist
date: 2026-06-07
---

# Prior Art Landscape for Buildroot Reconstruction

## Landscape Summary

| Approach | Producer/Consumer | Output | Maven Support |
|----------|------------------|--------|---------------|
| SLSA provenance | Producer | Attestation JSON | Yes (alpha) |
| Reproducible Central | Producer (manual) | Shell buildspec | Yes |
| Macaron BuildGen | Consumer (automated) | Buildspec | Yes |
| OSS-Rebuild | Consumer (automated) | Attestation | No (roadmap) |
| **Buildroot Reconstructor** | **Consumer (automated)** | **Containerfile** | **Yes** |

## Tools That Don't Fit

- **jbang**: Runs Java scripts with auto JDK download; no POM-based JDK inference
- **Maven Wrapper (`mvnw`)**: Pins Maven version, not JDK — useful as signal only
- **Reproducible Build Maven Plugin (Zlika)**: Producer-side, strips non-deterministic data
- **diffoscope**: Compares artifacts — verification, not reconstruction
- **reprotest**: Tests reproducibility in varied environments — verification, not reconstruction
- **Arch Linux `repro` / `debrebuild`**: Consumer-side buildroot reconstruction but for Linux distro packages, not Maven

## Our Differentiator

Containerfile output (executable environment specification) + fully automated consumer-side inference from `pom.xml` + CI config. No existing tool produces this combination.
