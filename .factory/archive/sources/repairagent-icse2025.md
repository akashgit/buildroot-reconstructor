---
tags:
  - factory
  - source
  - agentic-design
source: factory-archivist
date: 2026-06-13
---

# RepairAgent (ICSE 2025)

**Paper:** [RepairAgent](https://software-lab.org/publications/icse2025_RepairAgent.pdf)

## Findings

RepairAgent treats the LLM as an autonomous agent that plans and executes repair actions in iterative cycles. Each cycle follows: query LLM -> execute tool -> update context -> repeat. The agent selects which tools to invoke rather than following a fixed pipeline.

## Relevance to Buildroot Reconstructor

Directly applicable to the Analyzer -> Researcher -> Builder flow in the agentic inner loop. The key insight is that the agent should *choose* its next action (which fix to attempt) rather than following a predetermined sequence. This validates the design where the Analyzer classifies errors and suggests fix directions, but the Builder has autonomy in how it applies the fix.

## Key Takeaway

Agent-driven tool selection outperforms fixed pipelines for repair tasks. Our inner loop's mode switching (exploit/explore/meta-shift) via the progress signal G_t is a structured version of this principle.
