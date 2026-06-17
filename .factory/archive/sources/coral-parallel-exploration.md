---
tags:
  - factory
  - source
  - multi-candidate
source: factory-archivist
date: 2026-06-16
---

# CORAL — Parallel Agent Exploration Without Coordination

**Paper**: [CORAL: Autonomous Multi-Agent Evolution (2025)](https://xuquant.com/en/posts/foundation-models/coral-autonomous-multi-agent-evolution/)

## Key Insight

N agents exploring in parallel **without message passing**, with heartbeat-based interventions. Exceeds fixed evolutionary baselines by 3-10x.

**Critical finding**: Parallel exploration without coordination outperforms sequential exploration with coordination when evaluation is cheap relative to generation.

## Relevance to Top-K Builds

Applies directly to buildroot's Top-K parallel candidate builds:
- `podman build` (evaluation) is ~2-5 minutes
- Agent candidate generation is ~30 seconds
- Running K=3 builds in parallel costs ~1x wall-clock time, not 3x

## Design Guidance

- K=3 is a reasonable default — CORAL shows diminishing returns past 5-10 parallel candidates for constrained search spaces
- Dead-end tracking of losing candidates prevents re-exploration
- The AnalyzeAgent gets richer signal from K outcomes than from 1 — comparative analysis ("A failed because X, B succeeded because Y") produces better playbook entries
