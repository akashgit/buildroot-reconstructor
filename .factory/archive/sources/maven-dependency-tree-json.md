---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
---

# Maven `dependency:tree` JSON Output — Eliminates Text Parsing

## Finding

Since Maven Dependency Plugin 3.7.0, JSON output is natively supported:

```bash
mvn dependency:tree -DoutputType=json -DoutputFile=deps.json
```

This eliminates the need for text-format tree parsing entirely.

## JSON Structure

Nested tree with `groupId`, `artifactId`, `version`, `scope`, and `children` array at each node.

## Text Fallback

For Maven < 3.7.0, text format uses 3-char prefix characters (`+- `, `\- `, `|  `, `   `). Depth = `len(prefix) // 3`. Each line: `groupId:artifactId:type:version:scope`.

## `-DoutputFile` Behavior

Same format as stdout but without `[INFO]` prefixes — cleaner to parse.

## Recommendation

Try JSON first. Fall back to text parsing only if Maven version < 3.7.0. Use `-DoutputFile` for cleaner output in both cases.
