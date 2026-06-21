---
tags:
  - factory
  - source
  - agentic-design
source: factory-archivist
date: 2026-06-13
---

# OpenAI Codex: Iterative Repair Loops

**Source:** [OpenAI Codex Iterative Repair](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex)

## Findings

Separates judgment from proof: Review -> Repair -> Validation as distinct phases with structured outputs. Each phase has a clear contract — Review produces a diagnosis, Repair produces a patch, Validation produces a pass/fail verdict. The separation prevents conflation of "what's wrong" with "how to fix it."

## Relevance to Buildroot Reconstructor

This is exactly our Analyzer -> Builder -> Evaluator pattern. The structured output contract validates our design where:
- Analyzer produces error classification + fix suggestion
- Builder produces a modified Containerfile
- Evaluator produces L1-L4 score + ComparisonReport

## Key Takeaway

Phase separation with structured contracts between agents is a validated pattern. Our design follows this exactly.
