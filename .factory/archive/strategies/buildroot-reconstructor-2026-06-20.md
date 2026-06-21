---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-20
source: factory-archivist
verdict: PROCEED
hypothesis_count: 1
mode: targeted
---

# Strategy: buildroot-reconstructor — 2026-06-20

## Strategic Context

- **Current Score:** 0.608
- **Weakest Dimension:** capability_surface (0.411)
- **Recent Momentum:** Last 3 experiments (#16, #17, #18) all kept — strong v3 pipeline stability
- **Structural Ceiling:** v3 pipeline is mature but capped — 9/31 packages solved at L4, 22 packages L3-stuck with no path forward
- **Mode:** Targeted (single hypothesis for issue #60)

## Key Observations

1. **Template-bound ceiling:** v3 pipeline can't express multi-stage builds, custom tooling, or OSGI wrapping — 22/31 packages structurally blocked
2. **Codebase readiness:** ~85% ready for v4 (local research confirms) — missing pieces cleanly isolated: 6 new files, no breaking changes to v3
3. **Proof of concept validated:** Bouncy Castle reached 0.9998 in 4 iterations via human (Claude Code) writing raw Containerfiles and using eval directly — exactly what orchestrator agent will do autonomously
4. **Execution substrate confirmed:** CEO review explicitly requires Python subprocess approach (not Workflow), matching existing `claude_runner.py` patterns from experiments #008-#018

## Why This Hypothesis

**What:** Implement all 4 phases of issue #60 in a single PR — v4 agent-as-orchestrator architecture. The v3 pipeline becomes a tool the orchestrator uses (wrapped, not replaced).

**Why:** Highest-leverage change for the project. V3 structurally capped at 9/31 packages. Issue #60's architecture (agent monitors v3, takes over when stagnated, uses KB for cross-package learning) validated by Bouncy Castle proof-of-concept. Capability_surface is weakest eval dimension (0.411) — this adds massive new capability: orchestrator agent, KB system with retrieval, learning loop, 5 new CLI entry points.

**How to apply:** This is an architectural breakthrough, not an incremental improvement. All 4 phases must be implemented fully (CEO review explicitly forbids shortcuts). Real E2E testing on rh-h100-01 is mandatory (project memory: token cost never justifies skip). Expected impact: capability_surface 0.411 → 0.75+, composite 0.608 → 0.70+, unlocks path to 50%+ solve rate by enabling arbitrary Containerfiles for 22 stuck packages.

## Approved Hypothesis

### H1: Implement v4 agent-as-orchestrator — all 4 phases (issue #60)

- **Category:** EXPLORE
- **Type:** code
- **Backlog item:** solve issue 60, read it carefully and make sure you implement it in full and test it as the issue describes, dont allow any agent to take shortcuts
- **Growth dimension:** capability_surface
- **Addresses:** #60
- **Priority:** high

#### Phase 1 — Expose v3 as callable tool + standalone eval CLI

- Add `buildroot eval <containerfile> <coordinate> --host <host>` CLI command (~80-100 lines) wrapping `Evaluator.evaluate()` → JSON: `{l1_parse, l2_build, l3_command, l4_score, comparison_report, reward}`
- Ensure v3 pipeline supports per-iteration calling via `buildroot v3 <coord> --max-iterations 1 --workspace <path>` (research confirms exists)
- Add workspace artifact output (score, CF, comparison report as files) if not present

#### Phase 2 — Orchestrator agent (meta_agent.py + meta_prompt.py)

- `meta_agent.py` (~200-300 lines): Orchestrator outer loop
  - Entry point: `run_orchestrator(coordinate, host, workspace, target_score=0.98, max_budget_usd=15.0)`
  - Spawns Claude Code agent via `claude_runner.spawn_claude_agent()` with system prompt from `meta_prompt.py`
  - Pre-spawn context: runs `prepass.run_prepass()`, queries KB via `retrieval.query_kb()`
  - Spawned agent drives entire loop — decides when to use v3, when to take over and write raw Containerfiles
  - Full tool access: Bash, Read, WebSearch/WebFetch, Edit/Write
  - Termination: score ≥ target, budget exhausted, or 3 consecutive iterations with no improvement
  - Post-success: triggers Phase 4 learning loop

- `meta_prompt.py` (~300-400 lines): Domain expert system prompt builder
  - Function: `build_meta_prompt(coordinate, prepass_findings, kb_entries, workspace)`
  - Domain expertise: JAR structure, bytecode versioning, build systems (Maven/Gradle/Ant), OSGI bundles, code signing, multi-release JARs, Apache reproducibility flags
  - v3 template knowledge: what template can/can't express (tells agent when to delegate vs take over)
  - Tool documentation: `buildroot v3`, `buildroot eval`, `buildroot kb` commands
  - Eval infrastructure: L1→L2→L3→L4 scoring, comparison report format, failure diagnostics
  - Dynamic context: pre-pass findings, KB entries, workspace state
  - Strategy guidance: "Start with v3 for standard builds. Monitor score. Take over if stagnated or template can't express what's needed."

- CLI: `buildroot agent <coord>` spawns orchestrator. `buildroot agent <coord> --v3-only` preserves backward compat.

#### Phase 3 — Knowledge Base (YAML templates/tips/tricks + retrieval)

- `knowledge/schema.py` (~100-150 lines): YAML schema for 3 entry types
  - `KBEntry`: name, type (template|tip|trick), tags, build_systems, trigger_patterns, success_rate, times_used, coordinate, content
  - `TemplateEntry`: adds containerfile, stages, characteristics
  - `TipEntry`: adds trigger, solution, caveats
  - `TrickEntry`: adds error_pattern, fix, root_cause

- `knowledge/retrieval.py` (~150-200 lines): Ranked retrieval
  - `query_kb(kb_dir, build_system, manifest_keys, error_pattern, group_id)` — filters and scores entries
  - Scoring: exact tag match (+10), partial (+5), group_id (+3), trigger_pattern regex (+8), keyword (0-5)
  - Returns top 10 entries sorted by score

- `cli/commands/kb_cmd.py` (~120-150 lines): CLI commands
  - `buildroot kb list` — lists all entries with metadata
  - `buildroot kb search <query>` — runs retrieval and displays results
  - `buildroot kb add <path>` — validates and imports entry

- **Seed KB:** 10 Bouncy Castle entries at `~/.buildroot/kb/*.md`:
  1. ant-exact-version.md
  2. bnd-osgi-wrap.md
  3. bnd-before-multirelease.md
  4. real-jdk9-binary.md
  5. jdk9-jar-strict.md
  6. encoding-utf8.md
  7. jar-uf-not-cf.md
  8. signing-irreducible.md
  9. hsperfdata-suppress.md
  10. source-date-epoch.md

#### Phase 4 — Learning Loop

- Post-success recording in `meta_agent.py` (~100 lines):
  - Extract winning Containerfile, classify novel techniques
  - `record_template()` — saves winning CF as TemplateEntry
  - `extract_tips()` — parses orchestrator reasoning for reusable techniques (small Claude agent call with schema)
  - `extract_tricks()` — identifies error→fix mappings from build iteration history
  - Update `times_used` and `success_rate` on retrieved KB entries that contributed to solution

#### Implementation Scope

**Files created/modified:**

| File | Action | Lines |
|------|--------|-------|
| `src/buildroot/agent/meta_agent.py` | NEW | ~250 |
| `src/buildroot/agent/meta_prompt.py` | NEW | ~350 |
| `src/buildroot/cli/commands/eval_cmd.py` | NEW | ~90 |
| `src/buildroot/cli/commands/kb_cmd.py` | NEW | ~130 |
| `src/buildroot/agent/knowledge/schema.py` | NEW | ~130 |
| `src/buildroot/agent/knowledge/retrieval.py` | NEW | ~180 |
| `~/.buildroot/kb/*.md` | NEW | 10 seed entries |
| `src/buildroot/cli/commands/agent_cmd.py` | MODIFY | +30 |
| `src/buildroot/cli/main.py` | MODIFY | +15 |

**Total:** ~1500 new lines across 8 new + 2 modified files. No changes to existing v3 components (`pipeline_v3.py`, `evaluator.py`, `prepass.py`, `claude_runner.py`, `jar_comparator.py`, `feedback.py`, `scorer.py`).

#### Expected Impact

- **capability_surface:** 0.411 → 0.75+ (5 new CLI commands, orchestrator agent, KB system, learning loop — major new feature surface)
- **Composite score:** 0.608 → 0.70+
- **Solve rate unlock:** Path to 50%+ on 31-package benchmark by enabling arbitrary Containerfiles for 22 stuck packages

## Anti-patterns to Avoid

1. **Don't use Workflow tool for orchestration** — Issue #60 and CEO review both specify Python subprocess via `claude_runner.py`
2. **Don't implement partial phases** — Backlog item explicitly says "implement it in full and test it as the issue describes, dont allow any agent to take shortcuts"
3. **Don't break v3 backward compatibility** — 9 solved packages must still work. v3 becomes a tool. `--v3-only` flag preserves old path
4. **Don't skip KB seeding** — Empty KB is useless. All 10 Bouncy Castle entries required as seed data
5. **Don't over-engineer KB retrieval** — Metadata filtering + regex pattern matching (ACE-style playbook pattern, validated in experiments #027+). No vector embeddings
6. **Don't mock E2E testing** — Per project memory (2 entries): real E2E on rh-h100-01 mandatory after ANY agent/pipeline code change. Token cost never justifies skip
7. **Don't repeat raw information dump anti-pattern (exp #10, -19.4pp)** — Orchestrator prompt must use structured sections, not raw dumps

## CEO Verdict

**PROCEED** — All 5 checklist items passed:

1. **Depth check:** PASS — Every phase has specific files, function signatures, line estimates, CLI commands, KB seed entries (~1500 words of implementation spec)
2. **Research grounding check:** PASS — References local research (85% readiness), external research (Python subprocess, ACE playbooks), experiments #008-#018, Bouncy Castle POC
3. **Buildability check:** PASS — Builder can implement all 4 phases from this spec without clarifying questions
4. **Growth dimension check:** PASS — capability_surface explicitly tagged, genuine growth (5 CLI commands, orchestrator, KB, learning loop)
5. **Backlog item check:** PASS — Tagged as backlog item matching exact backlog text

**Targeted mode validation:** PASS (exactly 1 hypothesis matching issue #60, no extras)

## Critical Builder Requirements (from CEO)

1. **Run actual benchmarks after implementation:**
   - 2-3 packages from 31-package set (e.g., commons-lang3, jackson-databind, jackson-core) via `buildroot agent <coord>` to verify v3 path
   - Bouncy Castle (org.bouncycastle:bcprov-jdk15on:1.70) through orchestrator to test takeover path
   - Test all KB commands: `buildroot kb list`, `buildroot kb search`, `buildroot kb add`
   - Verify `buildroot eval` CLI works on real Containerfile
   - **All benchmarks on rh-h100-01 nodes** (SSH as `lab`, not `akasriva`)

2. **NO shortcuts** — Code that compiles but hasn't been tested on real packages is not acceptable
3. **NO scope reduction** — All 4 phases, all 10 KB seed entries, all CLI commands mandatory
