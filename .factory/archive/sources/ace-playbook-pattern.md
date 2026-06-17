---
tags:
  - factory
  - source
  - agent-architecture
source: factory-archivist
date: 2026-06-16
---

# ACE Framework — Generator-Reflector-Curator Playbook Pattern

**Paper**: [ACE: Agentic Context Engineering (Zhang et al., 2025)](https://arxiv.org/abs/2510.04618) — Stanford/SambaNova/Berkeley

## Key Architecture

Three components unified by an evolving "Context Playbook":

- **Generator**: Reads playbook rules before acting (maps to node agents reading `.factory/playbooks/`)
- **Reflector**: Compares output against ground truth, identifies strategic failures (maps to AnalyzeAgent diagnosing build failures)
- **Curator**: Decides whether to create a new "Delta Rule" or merge with existing (maps to AnalyzeAgent writing DO/DON'T entries)
- **Pruner**: Periodically synthesizes redundant rules into "Master Rules" (future optimization for playbook convergence)

## Critical Design Detail

Playbook entries are **append-only** with helpful/harmful counters that increment over time — content is never rewritten, only counters change. New insights are deduplicated via cosine similarity (0.8 threshold).

## Validation for Issue #27

The AnalyzeAgent IS the Reflector+Curator combined. Node agents ARE the Generator. The playbook files ARE the Context Playbook. Issue #27's design maps 1:1 to the ACE architecture, with the addition that the "ground truth" is the build outcome (L1-L4 level), not a labeled dataset.

**Implementation reference**: [ace-playbook](https://github.com/jmanhype/ace-playbook) — append-only delta rules with helpful/harmful/neutral labels and FAISS-based semantic dedup. For buildroot, exact-match dedup by agent+rule-hash is simpler and sufficient.

## Relevance

Directly validates AnalyzeAgent design for issue #27. The append-only playbook format with counters matches the proposed `[img-001] harmful=1 :: Do NOT emit bare Docker Hub names...` syntax.
