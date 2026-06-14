---
tags:
  - factory
  - source
  - agentic-design
source: factory-archivist
date: 2026-06-13
---

# SGAgent: Multi-Agent Repository Repair

**Paper:** [SGAgent](https://arxiv.org/html/2602.23647v2)

## Findings

Multi-agent repair with escalation: if fixer fails 3x, escalate to suggester; if suggester fails 2x, escalate to localizer. This cascading escalation pattern prevents the system from getting stuck at one level of abstraction.

## Relevance to Buildroot Reconstructor

Maps directly to our G_t mode switching:
- Fixer (3x fail) -> Suggester = our exploit -> explore transition
- Suggester (2x fail) -> Localizer = our explore -> meta-shift transition

Their 100-iteration cap is analogous to our T_max budget limit.

## Key Takeaway

Escalation thresholds should be empirically tuned. SGAgent's 3x/2x thresholds are a reasonable starting point, but our progress signal G_t with continuous rho=0.9 decay is more nuanced than hard cutoffs.
