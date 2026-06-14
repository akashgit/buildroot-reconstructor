---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - outer-loop
source: factory-archivist
date: 2026-06-13
---

# AutoScientists: Self-Organizing Agent Teams for Long-Running Experimentation

**Source**: [AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation](https://arxiv.org/abs/2605.28655)

## Key Findings for Outer Loop

### Stagnation Detection
"No improvement in the last 10 experiments" triggers team reorganization. For our outer loop: if ≥3 cycles produce J(S) < threshold, trigger a meta-shift from fixing individual error classes to proposing architectural changes.

### Dead-End Registries Per-Team
Teams maintain `D_k` with "failed experimental directions together with the tested axis, research direction, performance change, and rejection reason." Maps directly to our strategy archive — each cycle records what was tried, whether it worked, and why it failed.

### Cross-Team Visibility
"All results, including failures, are visible to every agent across all teams." For our outer loop: the Failure Analyst and Outer Strategist should see all prior cycle outcomes, not just the most recent.

### Noise-Aware Validation
Improvements within the "empirically measured noise band" require confirmation on a second seed. For outer loop: improvements of ≤1 package on the test suite should be confirmed by re-running the batch to rule out flaky builds.

### Analyst-Driven Coverage Audits
Periodically check which research directions have never been tested. The Outer Strategist should consider which error classes have never been targeted by a code change.

## Implementation Relevance
The stagnation trigger (≥8 package failures in ≤3 error classes) from the spec is directly inspired by AutoScientists' "saturated search direction" concept. Dead-end registry pattern already proven in inner loop; extending to outer loop strategy archive is natural.
