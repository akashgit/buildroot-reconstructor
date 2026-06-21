---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - supply-chain
source: factory-archivist
date: 2026-06-12
---

# SBOM Ground Truth Benchmarks

## Finding
ReversingLabs documented the critical challenge of SBOM accuracy — build manifests alone can be incomplete or inaccurate. Independent validation of build components against ground truth is essential for supply chain security.

## Relevance to Buildroot Reconstructor
Our approach of comparing inferred build environments against PNC ground truth is a form of independent validation — exactly what the supply chain security community recommends. This positions the project within the broader SLSA and SBOM accuracy ecosystem.

## Key Insight
PNC validation is not just a test — it's a demonstration of the supply chain security value proposition. If the reconstructor can accurately infer PNC build environments from consumer-side artifacts, it validates the entire approach of consumer-side build provenance reconstruction.

## Sources
- [ReversingLabs: Why Ground Truth Is Key — The Case for SBOM Benchmarks](https://www.reversinglabs.com/blog/why-ground-truth-is-key-the-case-for-sbom-benchmarks)
- [S3C2 Supply Chain Security Challenges](https://s3c2.org/challenges/)
- [SLSA Framework](https://slsa.dev/)
