---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-13
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-13 (Claude Code Agent Migration)

## Context
- **Current Score**: 0.8439 (post experiment #007)
- **Active Issue**: #19 — Replace raw AnthropicVertex API calls with Claude Code agent subprocess spawning
- **Keep Streak**: 7/7 — zero reverts
- **CEO Verdict**: PROCEED

## Design Space Assessment

| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | Inner loop, outer loop, failure analyst, strategist, guards all built |
| Bug fixes | 3 | 5 code review fixes on PR #18, J-score epsilon, diff format fixes |
| Instrumentation | 1 | 100 log statements across 220 functions (15% coverage), structured=no |
| Flow changes | 2 | Outer loop orchestrator exists but uses raw API calls + hardcoded dict |
| New agents | 1 | No Claude Code agents yet — all agents are raw AnthropicVertex one-shots |
| Prompt engineering | 2 | Builder system prompt exists, meta_guidance injection works |
| Eval improvements | 2 | 5-dimension eval in place, type_check at 0.2 |
| Knowledge management | 2 | KB directory + patterns.md exist, strategy archive in place |
| Infrastructure | 1 | No CI, no automated E2E, rh-h100-01 SSH builds only |
| Operational execution | 1 | Smoke test on 3 packages ran once; no systematic L3/L4 runs |
| Self-evolution | 0 | Outer loop code mutation exists but is a single-shot text completion |

**Underserved dimensions**: New agents (1), Infrastructure (1), Self-evolution (0)

## Key Observation

The project has a functional inner+outer loop but every LLM-calling agent uses `AnthropicVertex` single-shot completions with no tools. This is the single largest architectural bottleneck — agents cannot iterate, cannot read files, cannot search the web, cannot debug build errors. Issue #19 is the highest-leverage change available.

## Approved Hypothesis

### H1: Replace raw API calls with Claude Code subprocess agents across all loops
- **Category**: EXPLORE
- **Type**: code
- **Growth dimension**: capability_surface
- **Addresses**: Issue #19
- **Priority**: high

### Deliverables

1. **Shared `claude_runner.py`** — Wraps `subprocess.run(["claude", ...])` with structured output parsing, error handling, configurable per-agent options (model, turn limits, allowed tools)

2. **Inner Builder** (`builder.py:86-111`) — Replace `AnthropicVertex.messages.create()` with `claude -p` subprocess. System prompt includes Containerfile, build error, dead-end registry, spec, meta_guidance. Three modes (refine/explore/fresh_start) become task description variations. Agent gets Read/Edit/Bash/WebSearch tools.

3. **Outer Builder** (`outer_loop.py:372-435`) — Replace `OuterBuilder` class with `claude -p` subprocess. Remove 200-line file cap — Edit tool handles any file size. System prompt includes hypothesis, target files, error context.

4. **Outer Strategist** (`outer_strategist.py:148-183`) — Replace `propose_hypothesis()` hardcoded dict with `claude -p --json-schema` subprocess. Agent receives failure analysis, KB patterns, strategy archive, mutable surfaces list. Outputs structured `CodeChangeHypothesis`.

5. **Outer Researcher** (NEW `outer_researcher.py`) — Claude Code agent between Failure Analyst and Strategist. Reads failure analysis + KB, does web research on dominant failure patterns, outputs research report fed to Strategist.

6. **Guards update** — Add `outer_researcher.py` and `claude_runner.py` to `MUTABLE_SURFACES`.

7. **Tests** — Unit tests mocking `subprocess.run` for each agent. Integration test verifying prompt construction and output parsing.

8. **E2E** — Inner loop on 1 package (commons-lang3). Full outer loop cycle on smoke test (3 packages).

### Call Sites to Replace

| Agent | File | Line | Current | Problem |
|---|---|---|---|---|
| Inner Builder | `builder.py:86-111` | `AnthropicVertex.messages.create()` | Single-shot text completion, no tools, no iteration |
| Outer Builder | `outer_loop.py:376-435` | `AnthropicVertex.messages.create()` | 200-line file cap, full-file rewrite, no test verification |
| Outer Strategist | `outer_strategist.py:148-183` | Hardcoded Python dict | Not even an LLM call — 4 canned hypotheses only |
| Outer Researcher | Does not exist | N/A | No web research before hypothesis generation |

### Expected Impact
- capability_surface +0.15 (new agent + upgraded agents)
- tests maintained at 1.0 (mock subprocess in unit tests + E2E passes)
- lint maintained at 1.0
- No direct impact on type_check or observability this cycle
- Real impact on solve_rate when Inner Builder can iterate and debug (requires batch run on rh-h100-01)

### Anti-patterns to Avoid
- Don't do full-file rewrites via API — use Claude Code's Edit tool for surgical changes
- Don't hardcode hypotheses — LLM agent can reason about novel failure patterns
- Don't remove AnthropicVertex dependency entirely yet — other parts may import it
- Don't skip E2E verification — issue #19 explicitly mandates it
- Don't modify fixed surfaces — evaluator.py, jar_comparator.py, eval/score.py, packages_smoke.txt are locked

## CEO Assessment

**Focus directive compliance**: PASS — exactly 1 hypothesis, matches target (issue #19).

**Hypothesis quality**: Specific (exact files and line numbers), scoped (one PR), research-grounded (3 researcher reports), growth tagged (capability_surface), anti-patterns documented.

**Backlog item adequacy**: PASS — H1 covers ALL 6 deliverables from issue #19.

## Research Foundation

Three parallel researchers produced 1102 lines of analysis:
- **Local** (310 lines): All 3 call sites mapped, zero test breakage risk confirmed, meta_guidance flow traced
- **External** (474 lines): Full CLI reference, `spawn_claude_agent()` implementation, per-agent configs, Vertex AI setup
- **Context** (318 lines): Module migration map, 8-risk assessment, 5-phase implementation order, test strategy

## Previous Strategy
Cycle 7: Outer Loop with Failure Analyst, Knowledge Base, Guards, and Strategy Archive (issue #16) — KEEP, +0.0427
