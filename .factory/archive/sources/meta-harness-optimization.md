---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - outer-loop
source: factory-archivist
date: 2026-06-13
---

# Meta-Harness: End-to-End Optimization of Model Harnesses

**Source**: [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052)

## Key Findings for Outer Loop

### Harness as Optimization Target
The performance of LLM systems depends not only on the model but on the *harness* — the code that determines what information to store, retrieve, and present. Meta-Harness optimizes harness code via end-to-end search.

### Full History Exposure via Filesystem
Exposing full experiment history through a filesystem is superior to compressed summaries. Validates our strategy archive approach — keep full cycle records accessible, don't over-summarize.

### Our Outer Loop IS Harness Optimization
Our outer loop is literally optimizing a harness — the Builder's system prompt, the Analyzer's error patterns, the Observer's metadata extraction. Meta-Harness validates that this is a tractable optimization target.

## Implementation Relevance
Directly validates the outer loop's architectural premise. The strategy archive should retain full diffs and outcomes (not just summaries) for the first 20 cycles, with summarization only for older entries. The knowledge base injection into the inner loop Builder is the primary "harness knob" being optimized.
