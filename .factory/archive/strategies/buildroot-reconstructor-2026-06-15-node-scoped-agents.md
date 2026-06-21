---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-15
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-15

## CEO Verdict: PROCEED

Approved with no issues. Full validation checklist passed (10/10 items).

## Context

- **Current Score**: 0.5651 (composite), 0.8456 (eval)
- **Weakest Dimensions**: type_check (0.0), lint (0.3), capability_surface (0.41)
- **Experiment History**: 8/8 kept, zero reverts
- **Agentic Solve Rate**: 33.3% (1/3 smoke packages), stagnated
- **Deterministic Baseline**: 4/31 L4 (13%)
- **Active Issue**: #24 — Node-scoped pipeline agents

## Approved Hypothesis

### H1: Node-scoped agents — Claude Code reviewer at every pipeline step

- **Category**: EXPLORE
- **Type**: mixed (code + operational benchmark)
- **Backlog Item**: Issue #24

**What**: Implement 13 Claude Code reviewer agents (10 node agents + 3 post-build failure agents) integrated into the deterministic pipeline, plus a full benchmark run on all 31 packages.

**Code Deliverables**:
1. `NodeAgent` base class (`src/buildroot/agent/node_agents/base.py`) — system prompt templating, context injection, candidate ranking with evidence hierarchy (direct observation > CI inference > cross-reference > historical pattern > ecosystem heuristic > default)
2. 10 node agent implementations:
   - Node 1 — POM Agent: relocation detection, sparse POM detection
   - Node 2 — Parent Chain Agent: missing parents, BOM import validation
   - Node 3 — Property Agent: resolve remaining `${...}` via CI env vars, profiles, docs (fixes hibernate-core, postgresql)
   - Node 4 — Repo Agent: URL validation, multi-module subdirectory detection, GitHub API search (fixes 8 packages — highest impact)
   - Node 5 — CI Agent: correct workflow selection, alternative CI systems
   - Node 6 — JDK Agent: cross-reference POM compiler settings, CI matrix, .java-version, JAR manifest
   - Node 7 — Image Agent: Docker Hub registry API tag verification (fixes 6 packages)
   - Node 8 — Tag Agent: `git ls-remote --tags` verification (fixes guava, jersey-common)
   - Node 9 — Build Command Agent: build tool detection, flag validation (fixes json-smart, hibernate-validator, json-path)
   - Node 10 — Template Agent: rendered Containerfile syntax validation, unresolved placeholder detection
3. 3 post-build failure agents (L2/L3/L4 diagnosis)
4. `AgentAugmentedObserver` — wraps existing Observer, runs deterministic pipeline -> GapDetector -> node agents per gap
5. CLI integration: `--node-agents` flag
6. Evidence-type-based candidate ranking schema
7. Cost-conscious config: Sonnet for node reviewers (~$0.25-0.50/agent), Opus for failure agents only

**Operational Deliverable**: Full benchmark run on all 31 packages on rh-h100-01 with L1-L4 evaluation.

**Expected Impact**:
- capability_surface: 0.41 -> 0.50+ (13 new agent modules = 30+ public functions)
- L2 build rate: 7/31 (23%) -> 18-23/31 (58-74%)
- L4 match rate: 4/31 (13%) -> 8-15/31 (26-48%)
- observability: 0.61 -> 0.65+

## Why This Strategy

The deterministic pipeline fails on 24/27 packages at L2 due to well-characterized error categories that map 1:1 to specific pipeline nodes. The inner loop approach (experiments 6-8) hit a ceiling at 33.3% because it gives the LLM full Containerfile control, causing prose contamination in 90% of iterations. Node-scoped agents attack the root cause: each agent reviews structured data at its pipeline step, not entire Containerfiles.

Failure category mapping:
- Multi-module: 8 packages (Repo Agent)
- Base image: 6 packages (Image Agent)
- Build tool: 3 packages (Build Command Agent)
- Unresolved props: 2 packages (Property Agent)
- Git tag: 2 packages (Tag Agent)
- Build command/env: 3 packages (Build Command Agent)

Infrastructure ready: `spawn_claude_agent()`, SSH evaluator, GapDetector with OBSERVED/INFERRED/DEFAULTED classification.

## Anti-Patterns to Avoid

1. **Prose-wrapped Containerfile output** — dominant failure mode from experiments 6-8
2. **Framework-first delivery** — all 13 agents + benchmark must ship together (issue #24 spec)
3. **Mocked E2E tests** — real E2E on rh-h100-01 mandatory
4. **Self-assessed confidence** — rank by evidence type, not numeric confidence
5. **Expensive agent configuration** — Sonnet for node reviewers, total under $400-600
6. **Regression on passing packages** — 4 L4-passing packages must continue to pass

## CEO Scope Assessment

Large hypothesis (10+3 agents, augmented observer, CLI, benchmark) but issue #24 explicitly prohibits phased delivery. Builder needs 1800s+ timeout. Key risk: benchmark on rh-h100-01 takes ~7200s. Mitigation: if Builder delivers code but not benchmark, re-invoke with execution-only instructions.
