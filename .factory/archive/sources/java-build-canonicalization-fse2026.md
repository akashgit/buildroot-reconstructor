---
tags:
  - factory
  - source
  - reproducibility
source: factory-archivist
date: 2026-06-16
---

# Causes and Canonicalization of Unreproducible Builds in Java

**Paper**: [Sharma, Baudry, Monperrus — KTH (FSE 2026)](https://arxiv.org/abs/2504.21679)

## Six Root Causes of Unreproducibility

| Root Cause | Key Artifacts | Canonicalization Tool |
|---|---|---|
| 1. Build manifests | MANIFEST.MF (`Built-By`, `Build-Jdk`, `Created-By`), pom.properties | Chains-Rebuild: strip env-dependent attrs |
| 2. SBOM variations | CycloneDX `serialNumber`, `timestamp` | Open problem |
| 3. Filesystem | File permissions, ordering, sizes, embedded paths | OSS-Rebuild: normalize ZIP metadata |
| 4. JVM bytecode | Constant pool ordering, lambda naming, synthetic accessors | jNorm: Jimple IR transformation |
| 5. Versioning properties | git.properties (tag counts, builder info, branch) | Chains-Rebuild: strip git.properties |
| 6. Timestamps | 10+ locations: properties, docs, scripts, MANIFEST.MF | Chains-Rebuild: strip timestamp patterns |

## Results

- OSS-Rebuild alone: 9.48% reproducible
- Chains-Rebuild (enhanced): 24.72% reproducible
- jNorm (bytecode only): 29.7% of bytecode artifacts
- **Combined**: 26.89% of all artifacts become reproducible

## Critical Insight for L3→L4 Gap

All 6 L3 failures in exp 9 show `bytecode_match=True, structural_match=False, metadata_match=False`. This means bytecode is already identical — divergence is in categories 1, 3, 5, and 6 (manifests, filesystem, versioning, timestamps). These are ALL canonicalizable by Chains-Rebuild without needing jNorm.

## Actionable Canonicalization Steps

1. Strip `Built-By`, `Build-Jdk`, `Created-By`, `Bnd-LastModified`, `Build-Timestamp` from MANIFEST.MF
2. Remove pom.properties entirely (non-deterministic timestamp)
3. Strip git.properties if present
4. Normalize ZIP entry ordering and timestamps
5. Set `project.build.outputTimestamp` in Maven: `-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z`

## Cross-Ecosystem Context

[Benedetti et al., ICSE 2025](https://nesbitt.io/2026/02/24/reproducible-builds-in-language-package-managers.html): Cargo/npm = 100% reproducible; PyPI = 12.2%; Java/Maven in the middle. Gap is primarily timestamps and metadata.
