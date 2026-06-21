---
tags:
  - factory
  - source
  - build-repair
source: factory-archivist
date: 2026-06-16
---

# Build-bench — LLM Build Repair with Capped Iterations

**Paper**: [Build-bench: LLM Build Repair](https://arxiv.org/pdf/2511.00780)

## Key Design

Caps tool invocations at 20 per iteration and repair iterations at 3 per package. Each iteration rebuilds the prompt using three inputs:

1. Updated build log
2. Latest package state
3. Historical modifications

## Relevance to AnalyzeAgent

The three-input prompt pattern directly maps to AnalyzeAgent's inputs:
- Build logs → build log summaries (existing `build_log_summary` field, ≤500 chars)
- Current spec → current BuildrootSpec state
- Historical modifications → accumulated playbook entries

## Budget Implications

The cap at 3 iterations per package contrasts with buildroot's 15-iteration budget. Build-bench's constraint suggests that most learnable fixes are discovered within 3 iterations — iterations 4-15 are likely wasted on packages that need architectural changes rather than iterative repair. This supports early termination for stagnant packages.
