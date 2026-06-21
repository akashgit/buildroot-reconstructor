---
tags:
  - factory
  - source
  - issue-27
source: factory-archivist
date: 2026-06-16
---

# Issue #27 Context Analysis — Exp 9 Root Cause Breakdown

## Exp 9 Results: 7/31 L4 (22.6%)

| Level | Count | Key Packages |
|-------|-------|-------------|
| L4 (solved) | 7 | jackson-databind, avro, jettison, plexus-utils, json, snappy-java, snakeyaml |
| L3 (JAR mismatch) | 6 | jackson-core, nimbus-jose-jwt, jakarta.mail, commons-beanutils, commons-fileupload, jersey-common |
| L2 (source fails) | 12 | guava, protobuf-java, netty-buffer, json-smart, kafka-clients, assertj-core, + 6 more |
| L1 (container fails) | 6 | logback-classic, json-path, junit, commons-lang3, tomcat-catalina, hibernate-core |

## Root Causes by Level

### L1 (6 packages)
- **5 SSH auth failures** (infrastructure, not code) — logback-classic, json-path, junit, commons-lang3, tomcat-catalina
- **1 Containerfile syntax** (hibernate-core) — `ENV JAVA_OPTS -Xmx4g` instead of `ENV JAVA_OPTS="-Xmx4g"`

### L2 (12 packages) — Four Root Causes
| Root Cause | Count | Gap |
|-----------|-------|-----|
| Podman short-name | 5 | Gap 3 (fixes don't persist) |
| `./mvnw` not found/executable | 2 | Gap 1 (no runtime feedback) |
| Wrong build system (OBSERVED) | 1 | Gap 2 (should_activate blocks) |
| Multi-module missing deps | 4 | Architectural limit |

### L3 (6 packages) — One Root Cause
ALL show `bytecode_match=True, metadata_match=False`. Fix: `-Dproject.build.outputTimestamp` + MANIFEST.MF normalization.

## Critical Operational Findings

1. **ALL dead_end error classes are `unknown`** — analyzer.py isn't categorizing errors, so mode switching operates blind
2. **Every L1-stuck package exhausted 15 iterations** without improving — no learning across iterations
3. **Easy packages solve fast** (1-2 iterations), hard packages never improve — bimodal distribution

## Success Criteria (from issue #27)

- L4 ≥ 35% (11/31)
- Zero L1 from Containerfile syntax
- Zero L2 from Podman short-name
- Agent fixes persist across iterations
- Playbook files grow across packages
- Recipe store populated for L2+ packages

## Key Risks

1. AnalyzeAgent cost: $2/call × 15 iterations × 31 packages = $930 — needs early termination
2. Top-K combinatorial explosion: K^N specs across N node agents — cap at 5 total variants
3. SSH infrastructure: must verify access to ALL rh-h100 nodes before benchmark
