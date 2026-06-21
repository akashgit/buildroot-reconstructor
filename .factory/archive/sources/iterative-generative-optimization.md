---
tags:
  - factory
  - source
  - agent-architecture
source: factory-archivist
date: 2026-06-16
---

# Iterative Generative Optimization — Within-Task vs Cross-Task Loops

**Paper**: [Iterative Generative Optimization (March 2026)](https://arxiv.org/html/2603.23994)

## Key Distinction

Two loop types for agent learning:

1. **Within-task loops**: Optimize one task across iterations (= buildroot's per-package iteration loop with spec_overrides)
2. **Cross-task loops**: Accumulate experience across tasks (= playbook entries persisting across packages and runs)

## Relevance to AnalyzeAgent

The AnalyzeAgent operates at BOTH levels:
- **Within-task**: `spec_overrides` persist across iterations for one package
- **Cross-task**: Playbook entries persist across packages and across runs

This dual-loop architecture is identified as the key differentiator for "continual learning through repeated trial and error."

## Implementation Guidance

Spec overrides are the within-task persistence mechanism. They must be applied after `Observer.observe()` (which regenerates from scratch) but before node agents fire. Without this, the within-task loop has no memory — which is exactly Gap 3 from issue #27.
