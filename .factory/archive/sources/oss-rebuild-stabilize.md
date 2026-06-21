---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level4
source: factory-archivist
date: 2026-06-09
---

# Google OSS-Rebuild's `stabilize` Tool

Google's OSS-Rebuild project uses a `stabilize` command to normalize artifacts before comparison — semantic (not byte-for-byte) comparison philosophy.

## What `stabilize` Does
- Strips `jar-git-properties` and other build-specific metadata
- Normalizes timestamps and compression artifacts
- Produces a "stabilized" artifact for meaningful byte-comparison
- Identifies which JAR elements are "non-semantic" and safe to strip: git properties files, build timestamps, compression level differences, file ordering

## Current Status
- Written in Go, available at https://github.com/google/oss-rebuild/tree/main/cmd/stabilize
- **Maven not yet supported** — supports PyPI, npm, Crates.io
- Maven Central is on their roadmap but not yet implemented
- Our project fills this gap for Maven artifacts

## Relevance to Level 4
The `stabilize` philosophy validates our normalization approach — strip non-semantic elements before comparison rather than expecting byte-identical output. The concepts (timestamp normalization, metadata stripping, compression normalization) directly apply even though the tool itself doesn't support Maven yet.

## References
- [OSS-Rebuild stabilize tool](https://github.com/google/oss-rebuild/tree/main/cmd/stabilize)
- [Google Security Blog — OSS Rebuild](https://security.googleblog.com/2025/07/introducing-oss-rebuild-open-source.html)
