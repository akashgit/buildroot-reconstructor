---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - pnc
  - ground-truth
source: factory-archivist
date: 2026-06-12
---

# PNC Ground-Truth Validation Approach

## Concept
PNC Containerfiles define the exact environment used to build productized Java artifacts. Comparing the reconstructor's inferred environment against PNC ground truth measures reconstruction accuracy against a known-correct reference — not just reproducibility against Maven Central.

## Alignment with SLSA
This approach aligns with SLSA Level 3+ — verifying inferred environments match hermetic, documented build environments. Independent validation of build components is essential per supply chain security best practices (ReversingLabs SBOM accuracy research confirms build manifests alone can be incomplete).

## Scoring Dimensions (Weighted)
| Dimension | Weight | Logic |
|-----------|--------|-------|
| JDK major version | 0.25 | Normalize to major (8, 11, 17), exact match |
| JDK vendor | 0.10 | Map distributions to vendor category (temurin→openjdk family) |
| Build tool match | 0.25 | Maven vs Gradle detection |
| Build tool version | 0.15 | Exact version match |
| Base OS family | 0.10 | RHEL vs Ubuntu category comparison |
| SCM URL match | 0.15 | Correct upstream source repo |

## Expected Mismatches (Not Bugs)
1. **JDK version**: Reconstructor uses JAR manifest `Build-Jdk-Spec` (upstream CI JDK) — PNC uses its own JDK, which may differ. Critical insight from archive: `build-jdk-spec-vs-language-level.md`.
2. **OS family**: Reconstructor outputs Ubuntu-based images; PNC uses RHEL. Structural mismatch, low weight (0.10).
3. **Maven version**: Reconstructor detects Maven wrapper version; PNC specifies exact Maven version. Both correct in their contexts.

## Deliverables Scoped
1. PNC Containerfile parser (`PNCGroundTruth` dataclass)
2. Accuracy scorer (per-dimension + weighted aggregate)
3. Validation pipeline CLI command
4. JSON report at `results/pnc-validation/report.json`
5. Test suite with synthetic fixture Containerfiles

## Sources
- [SLSA Framework](https://slsa.dev/)
- [ReversingLabs: Ground Truth for SBOM Benchmarks](https://www.reversinglabs.com/blog/why-ground-truth-is-key-the-case-for-sbom-benchmarks)
- [S3C2 Supply Chain Challenges](https://s3c2.org/challenges/)
