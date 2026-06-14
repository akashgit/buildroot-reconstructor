---
tags:
  - factory
  - source
source: factory-archivist
date: 2026-06-07
---

# OSS-Rebuild (Google)

## Key Findings

- Reconstructs build environments using heuristics, performs hermetic rebuilds with semantic comparison (not bit-for-bit)
- Emits Sigstore-backed SLSA attestations
- Currently supports: PyPI, npm, Crates.io
- **Maven Central on roadmap but not yet implemented** — our tool fills this gap
- "Stabilize" tool strips non-deterministic metadata from packages for functional comparison
- Architecturally similar approach (heuristic build definition determination) but for different ecosystems

## Relevance

- Validates the consumer-side heuristic approach as viable (Google invested in it for other ecosystems)
- Maven gap means no direct competition
- Their semantic comparison technique (stabilize) could inform our Level 3 verification

## Reference

- Repository: https://github.com/google/oss-rebuild
