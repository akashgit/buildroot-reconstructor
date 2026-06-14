---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - outer-loop
source: factory-archivist
date: 2026-06-13
---

# EvoX: Meta-Evolution for Automated Discovery

**Source**: [EvoX: Meta-Evolution for Automated Discovery](https://arxiv.org/abs/2602.23413)

## Key Findings for Outer Loop

### Dual-Loop Architecture
Inner loop evolves solutions under a fixed strategy; outer loop evolves the strategy itself when the inner loop stagnates. This is exactly our architecture: inner loop evolves Containerfiles (fixed code), outer loop evolves the inner loop's code.

### Strategy Archive Contents
Tuples of `(strategy_code, population_state_descriptor, J_score)`. Maps to our strategy archive: `(code_diff, failure_taxonomy_snapshot, j_score)`.

### Demand-Driven Strategy Switching
"Strategy switching is demand-driven rather than periodic." The outer loop should not evolve code on a fixed schedule — it should trigger only when solve_rate stagnates. Critical since each batch run is expensive (~40 minutes for 3 packages on rh-h100-01).

### Strategy as Code
EvoX represents strategies as Python classes with `add` and `sample` methods, mutated by LLMs. Our outer loop similarly modifies Python code in `builder.py`, `analyzer.py`, etc. The LLM acts as the mutation operator on the reconstructor's source code.

### J(S) Formula (Confirmed)
`J = (s_end - s_start) · log(1 + s_start) / √W` — identical to AdaEvolve and the spec. The log term prevents low-baseline strategies from dominating the archive.

### Never Reset Solution Population on Strategy Switch
When the outer loop changes the reconstructor code, it should NOT discard prior knowledge base entries. Strategy evolution is additive.

## Implementation Relevance
The demand-driven (stagnation-triggered) model is more practical than periodic cycles for our case. The strategy-as-code pattern validates our approach of having the LLM modify Python source files directly.
