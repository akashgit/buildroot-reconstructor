---
tags:
  - factory
  - source
  - agentic-design
source: factory-archivist
date: 2026-06-13
---

# Mini-SWE-Agent: Lightweight Code Repair

**Source:** [Mini-SWE-Agent](https://www.emergentmind.com/topics/mini-swe-agent-27d26942-1f63-4337-bee8-576ebb1468c3)

## Findings

Lightweight edit-test-fix loop in sandboxed Docker. Key practices:
- Dynamic loop-breaking via tracking repeated command sequences
- Pre-execution syntax checkers before running builds
- Context selection to prevent prompt growth (only pass relevant error lines, not full logs)

## Relevance to Buildroot Reconstructor

Relevant for inner loop context management. Our `build_log_summary` field (<=500 chars) in BuildAttempt follows the same context selection principle. The repeated-sequence detection maps to our dead-end registry — both prevent the agent from cycling through the same failed approaches.

## Key Takeaway

Context management is critical for multi-iteration agents. The "memory pointer" pattern (store full log externally, pass key lines to LLM) prevents prompt bloat across iterations and is adopted in our design.
