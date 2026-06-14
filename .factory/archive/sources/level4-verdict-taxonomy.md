---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level4
source: factory-archivist
date: 2026-06-09
---

# Level 4 Verdict Taxonomy

Research-backed criteria for classifying artifact comparison results across the 10 test packages.

## Verdict Definitions

| Verdict | Criteria |
|---------|----------|
| **IDENTICAL** | SHA-256 of both JARs match byte-for-byte. Rare due to timestamps and compression. |
| **EQUIVALENT** | Same file listing, all `.class` files produce identical CFR decompilation, resource files identical after stripping known non-deterministic elements, MANIFEST differs only in excluded keys (`Build-Jdk`, `Built-By`, `Created-By`, `Build-Timestamp`, `Bnd-LastModified`). |
| **DIVERGENT** | Different class listings, bytecode logic differs, or resources don't match after normalization. |
| **FAILED** | Build failed, JAR not extractable, or Maven Central download failed. |

## Per-Package Report Structure
For each of the 10 packages, produce:
- `file_listing_match`: % of entries present in both JARs
- `size_similarity`: average size delta across matching entries
- `bytecode_match`: % of `.class` files with identical decompiled output
- `resource_match`: % of non-class files that are byte-identical (after normalization)
- `manifest_match`: which MANIFEST.MF fields match vs differ
- `verdict`: IDENTICAL / EQUIVALENT / DIVERGENT / FAILED

Plus a summary report with overall reproducibility score across all 10 packages.

## Key Insight
The EQUIVALENT verdict is the expected best-case for most packages. IDENTICAL requires reproducible-builds-aware Maven plugins with `project.build.outputTimestamp` set — most packages don't have this. The comparison pipeline should treat EQUIVALENT as a strong success signal.
