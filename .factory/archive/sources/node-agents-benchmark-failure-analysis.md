---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-24
  - benchmark
source: factory-archivist
date: 2026-06-15
research-type: context
---

# Benchmark Failure Analysis & Node Agent Impact Mapping

## Finding

Context research traced the full experiment history (experiments 6-8) and mapped the 31-package benchmark failure categories to specific node agents. The deterministic baseline is 4/31 L4 (13%), with 24 packages failing at L2 (container build).

## Current Baseline

| Level | Count | Rate |
|-------|-------|------|
| L1 parse | 31/31 | 100% |
| L2 build | 7/31 | 23% |
| L3 command | 5/31 | 16% |
| L4 match | 4/31 | 13% |

L4 passes: jackson-databind, commons-lang3, plexus-utils, jettison

## Failure Category → Node Agent Mapping

| Category | Count | % | Agent | Fix Strategy |
|----------|-------|---|-------|-------------|
| Multi-module / wrong dir | 8 | 26% | Node 4 (Repo) | Detect subdirectory, set WORKDIR or `-pl` flag |
| Base image not found | 6 | 19% | Node 7 (Image) | Docker Hub API tag verification, try alternatives |
| Build tool not found | 3 | 10% | Node 9 (Build Cmd) | Detect gradlew/gradle vs mvn, switch command |
| Containerfile syntax | 2 | 6% | Node 3 (Property) | Resolve remaining `${...}` from CI/profiles/docs |
| Git tag not found | 2 | 6% | Node 8 (Tag) | `git ls-remote`, try alternative tag patterns |
| Build cmd/env issues | 3 | 10% | Nodes 5+9 (CI + Build Cmd) | Cross-reference CI config with build tool |

**Total addressable: 24/27 failing packages (89%)**

## Realistic Impact Estimate

| Scenario | L2+ Rate | L4 Rate |
|----------|----------|---------|
| Current baseline | 7/31 (23%) | 4/31 (13%) |
| Optimistic (all agents work) | 23/31 (74%) | 15/31 (48%) |
| Realistic | ~18/31 (58%) | 8-15/31 (26-48%) |

## Critical Lesson from Experiments 6-8

The inner loop approach (Builder agent modifying full Containerfiles) suffered from:
1. **Prose contamination**: 90% of wasted iterations from LLM returning prose-wrapped Containerfiles
2. **Wrong build system detection**: Gradle projects misidentified as Maven
3. **Regression on solved packages**: spring-security-core was EQUIVALENT with deterministic template but Builder agent corrupted it

Node agents eliminate these problems by reviewing structured data (repo URLs, JDK versions, git tags) rather than full Containerfiles.

## Cost Estimate

- 31 packages × ~10 node agents × ~$1 each = ~$310 for node agents
- Plus ~5-10 failure agent calls per failing package = ~$150
- **Total estimated: $400-600** (full 31-package benchmark with all agents)
- Optimization: gap-status activation reduces cost for OBSERVED fields

## Acceptance Criteria

From issue #24: full 31-package L1-L4 benchmark run on rh-h100-01 is the PRIMARY acceptance criterion. No phasing, no "framework first," no deferring agents to future cycles.

## Sources
- `results/benchmark-full/summary.json` (baseline scores)
- Experiments 6-8 archive notes
- Issue #24 specification
- `.factory/strategy/observations.md` (interaction study)
