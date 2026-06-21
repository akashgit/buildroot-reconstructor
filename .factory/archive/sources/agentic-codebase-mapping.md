---
tags:
  - factory
  - source
  - agentic-design
  - architecture
source: factory-archivist
date: 2026-06-13
---

# Agentic Reconstructor: Codebase Mapping

**Source:** Internal research — mapping existing modules to agentic roles.

## Findings

The existing buildroot-reconstructor codebase maps cleanly to the agentic architecture:

| Module | Current Role | Agentic Role |
|--------|-------------|--------------|
| `pipeline/orchestrator.py` | Coordinates extraction -> generation | **Observer agent** — `reconstruct()` becomes Observer core |
| `pipeline/models.py` | Dataclasses (BuildrootSpec, PomData, CIData) | **Extend** — add BuildAttempt dataclass |
| `generators/containerfile.py` | Jinja2-based Containerfile generation | **Builder agent** — wrap for initial generation, add mutation |
| `generators/templates/*.j2` | 3 templates (jdk_base, jdk_on_ubuntu, custom_base) | **Evolve-block retrofit** (Phase 2) |
| `utils/jar_comparator.py` | 3-layer JAR comparison | **Evaluator agent** — directly reusable |
| `pipeline/gap_detector.py` | Identifies defaulted/inferred fields | **Analyzer input** — gap report feeds error classification |
| `parsers/pom.py`, `parsers/ci.py` | POM parsing, CI workflow extraction | Unchanged — called by Observer |
| `resolvers/jdk.py`, `resolvers/dependencies.py` | JDK inference, dep tree | Unchanged — called by Observer |

New modules for Phase 1:
```
src/buildroot/agent/
  loop.py        — Inner loop orchestrator
  observer.py    — Wraps existing reconstruct()
  builder.py     — Containerfile generation + LLM mutation
  evaluator.py   — Build execution + L1-L4 scoring
  analyzer.py    — Error classification + dead-end registry + G_t
  models.py      — BuildAttempt, DeadEndEntry, ProgressSignal
```

## Key Takeaway

Minimal disruption — existing modules are wrapped, not rewritten. The agentic layer sits on top of the existing pipeline. Observer wraps orchestrator, Evaluator reuses jar_comparator, Builder extends containerfile generator.
