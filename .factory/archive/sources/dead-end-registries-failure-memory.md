---
tags:
  - factory
  - source
  - agentic-design
  - failure-memory
source: factory-archivist
date: 2026-06-13
---

# Dead-End Registries and Failure Memory Patterns

**Sources:**
- Reflexion, ExpeL (episodic memory for agents)
- [DebounceHook Pattern (AWS)](https://dev.to/aws/why-ai-agents-fail-3-failure-modes-that-cost-you-tokens-and-time-1flb)
- [Memory Pointer Pattern](https://towardsdatascience.com/a-practical-guide-to-memory-for-autonomous-llm-agents/)

## Findings

Research consistently shows that without failure memory, agents repeat dead ends. Key patterns:

1. **Episodic memory** (Reflexion, ExpeL): agents write post-mortems after each attempt. Our dead-end registry is a structured form of this.
2. **DebounceHook pattern**: block repeated tool calls to prevent token waste. Applicable to our dead-end check before suggesting fixes.
3. **Memory Pointer pattern**: store large data in state, return short pointers to context. Relevant for build logs — store full log externally, pass key error lines to LLM.
4. **Context poisoning risk**: if a dead-end entry is wrong, it blocks valid approaches. Our 2-failure threshold before registry entry mitigates this — a single failure doesn't permanently block an approach.

## Relevance to Buildroot Reconstructor

The dead-end registry is essential infrastructure for the inner loop. Without it, the Builder will cycle through the same failed Containerfile mutations. The 2-failure threshold balances false-positive risk (blocking a valid approach) against wasted iterations (trying a truly dead approach).

## Key Takeaway

Failure memory is a prerequisite for iterative agents. The 2-failure threshold and memory pointer pattern are both adopted in our design.
