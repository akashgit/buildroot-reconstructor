---
tags:
  - factory
  - source
  - agent-architecture
source: factory-archivist
date: 2026-06-16
---

# Meta's Engineering Agent at Scale

**Paper**: [Meta Engineering Agent at Scale (July 2025)](https://arxiv.org/pdf/2507.18755)

## Key Findings

- Uses Llama with ReAct framework
- Averages **11.8 feedback iterations** for a **42.3% solve rate**
- Employs a separate LLM-as-Judge for patch quality before acceptance

## Relevance to Buildroot

Key simplification confirmed: for issue #27, the evaluation step (L1-L4 scoring) already serves as the automated judge — no separate judge agent needed. The L1→L2→L3→L4 progression is a deterministic quality ladder that replaces the LLM-as-Judge role.

The 11.8 iteration average validates that our 15-iteration budget is in the right ballpark, though Meta's higher solve rate (42.3% vs our 22.6%) suggests that their feedback loop is more effective — consistent with the argument that the AnalyzeAgent (closing the feedback gap) is the highest-leverage improvement.
