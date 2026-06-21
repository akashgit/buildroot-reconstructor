---
tags:
  - factory
  - source
  - agentic-design
  - mcts
source: factory-archivist
date: 2026-06-13
---

# AprMcts: MCTS for Program Repair (2025)

**Paper:** [AprMcts](https://arxiv.org/html/2507.01827v2)

## Findings

MCTS applied to program repair with concrete implementation details:
- UCT selection with C=0.7 exploration constant
- Branch factor=1, max 3 expansions per node
- Q-value backpropagation with beta=0.8 forgetting factor: Q'(a) = beta * [sum(Q_j * N_j) / sum(N_j)] + (1-beta) * Q(a)
- Adaptive evaluation: LLM-as-Judge (score/100) when few tests, test pass rate when many tests
- 0.5x penalty for patches identical to parent

## Relevance to Buildroot Reconstructor

Validates tree-search for iterative repair. Our PUCT design (Phase 2) is more sophisticated with rank-based priors and Q-values as max-reward, but AprMcts's simpler UCT with C=0.7 is a reasonable Phase 1 starting point. The beta=0.8 forgetting factor for Q-value updates is directly applicable to our progress signal.

## Key Takeaway

The 0.5x penalty for identical patches prevents cycling. The forgetting factor (beta=0.8) is critical — without it, early good scores dominate and the agent stops exploring. Both patterns adopted into our design.
