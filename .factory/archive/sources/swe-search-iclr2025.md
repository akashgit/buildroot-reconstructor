---
tags:
  - factory
  - source
  - agentic-design
  - mcts
source: factory-archivist
date: 2026-06-13
---

# SWE-Search: MCTS for Repository-Level SWE (ICLR 2025)

**Paper:** [SWE-Search](https://openreview.net/forum?id=G7sIFXugTX)

## Findings

MCTS applied to repository-level software engineering tasks with a hybrid value function combining numerical scores and qualitative LLM evaluation. Three-agent architecture:
- SWE-Agent: exploration (generates candidate patches)
- Value Agent: evaluation (scores candidates)
- Discriminator Agent: debate (compares candidates)

Performance scales with inference-time compute — more search budget yields better results.

## Relevance to Buildroot Reconstructor

Validates our multi-agent inner loop design. The three-agent split maps to our Builder (exploration), Evaluator (numerical scoring via L1-L4), and Analyzer (qualitative assessment). Their hybrid value function maps to our structured ComparisonReport which combines structural, metadata, and bytecode comparison.

## Key Takeaway

The inference-time compute scaling property means our iteration budget (T_max=15) directly controls result quality. The three-agent separation of concerns is independently validated here.
