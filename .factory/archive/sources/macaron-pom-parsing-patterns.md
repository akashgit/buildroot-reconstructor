---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
---

# Macaron POM Parsing Patterns — Reusable Implementation Reference

## Finding

Oracle's Macaron project (`src/macaron/parsers/pomparser.py`, UPL license) provides battle-tested patterns for POM parsing that our tool should adopt and extend.

## Patterns to Reuse

### Namespace-Agnostic Tag Matching
```python
def _tag_matches(tag, local_name):
    return tag == local_name or tag.endswith("}" + local_name)
```
Handles both `<groupId>` and `<{http://maven.apache.org/POM/4.0.0}groupId>` transparently.

### Iterative Parent Chain Walking
- Uses `visited: set[Path]` for cycle detection
- Depth limit of 50 (configurable)
- Iterative loop (not recursive) — avoids stack overflow on deep chains

### Encoding Robustness
- Tries UTF-8 first, falls back to Latin-1 for legacy POMs

## Gaps We Must Fill

Macaron does NOT:
1. Resolve Maven properties (`${...}` placeholders)
2. Fetch parent POMs from Maven Central (only walks local filesystem)

Our extensions:
1. Remote parent fetching: `repo1.maven.org/maven2/{groupPath}/{artifactId}/{version}/{artifactId}-{version}.pom`
2. Property resolution with recursive substitution and cycle detection
3. Cache fetched POMs in `~/.cache/buildroot/poms/` keyed by GAV

## Security Approach

Use `defusedxml` for initial parsing of untrusted POM XML (prevents entity expansion attacks), then `lxml` for XPath queries on trusted parsed content.

## Reference

- Source: https://github.com/oracle/macaron/blob/main/src/macaron/parsers/pomparser.py
- License: UPL (Universal Permissive License)
