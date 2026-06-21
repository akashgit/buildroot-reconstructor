---
tags:
  - factory
  - source
  - research
  - issue60
  - v4-architecture
project: buildroot-reconstructor
source: factory-archivist
date: 2026-06-20
---

# Local Research — Issue #60 v4 Agent-as-Orchestrator

**Research scope:** Codebase readiness for v4 architecture transition (template-bound pipeline → agent-orchestrated tool)

## Key Findings

### Codebase Readiness: 85%
- **13 files reusable as-is:** pipeline_v3.py (864L), evaluator.py (316L), jar_comparator.py (465L), feedback.py (247L), prepass.py (485L), claude_runner.py (176L), containerfile.py (274L), and 6 others
- **6 new files needed:** meta_agent.py (~250L), meta_prompt.py (~350L), eval_cmd.py (~90L), kb_cmd.py (~135L), schema.py (~125L), retrieval.py (~175L)
- **Total new code:** ~1500 lines across 12 files

### Critical Infrastructure Already Present
1. **v3 iteration mode** — `max_iterations=1` with persistent workspace parameter (no code changes needed)
2. **Evaluator** — Remote build + L1-L4 scoring via SSH to rh-h100-01 nodes
3. **Pre-pass** — Deterministic data gathering (POM, manifest, CI, JAR)
4. **Claude agent spawner** — `spawn_claude_agent()` with JSON schema support (exp #008-#018)
5. **RecipeStore** — Cross-package recipe storage with group hints

### Gap Analysis

**Phase 1: Eval CLI** (1-2 days, ~100 lines)
- Add `buildroot eval <containerfile> <coord> --host rh-h100-01`
- Returns JSON: `{l1, l2, l3, l4, score, comparison_report, reward}`

**Phase 2: Orchestrator** (3-5 days, ~600 lines)
- `meta_agent.py` — Python outer loop spawning Claude Code via subprocess
- `meta_prompt.py` — Domain expert system prompt (JAR, build systems, OSGI, bytecode)
- Monitor v3 progress, decide: continue / take over / done

**Phase 3: Knowledge Base** (4-6 days, ~700 lines)
- YAML schema with frontmatter (templates, tips, tricks)
- Retrieval by build_system, manifest_keys, error_pattern, group_id
- Ranking: exact tag match > partial > group > text similarity

**Phase 4: Learning Loop** (1-2 days, ~100 lines)
- After success, record winning CF as KB template
- Update success_rate and times_used counters

### Reusable Functions Mapped to v4

**From pipeline_v3.py:**
- `run_v3_pipeline()` → reuse as-is for v3 path
- `_render_containerfile(values)` → reuse for CF preview
- `reverse_parse_containerfile(cf)` → reuse for warm-start
- `_ensure_defaults(values, findings)` → reuse for field filling

**From evaluator.py:**
- `Evaluator.evaluate(cf, coord)` → reuse via CLI wrapper
- `Evaluator.l4_fallback_signals()` → reuse for fallback scoring

**From prepass.py:**
- `run_prepass(coordinate, workspace)` → reuse in orchestrator
- `PrePassFindings.to_prompt()` → reuse for context

## Benchmark Context

**From issue #60 (31 packages):**
- Solved (L4 ≥ 0.98): 9 packages (29%)
- L3 stuck: 21 packages (68%) — JAR produced, comparison failed
- L2 stuck: 1 package (3%) — build failed

**Bouncy Castle case study:** v3 couldn't express solution, human reached 0.9998 in 4 iterations

**Acceptance gates:**
1. No regression on 9 solved packages
2. 10+ of 22 stuck packages improve
3. Bouncy Castle ≥ 0.99 autonomously
4. Second OSGI package benefits from BC KB
5. Easy packages ≤ 1.5x v3 cost

## Implementation Timeline

**Total estimate:** 9-15 days, 12 files, ~1500 lines

**Complexity breakdown:**
- Phase 1: Low (1-2 days)
- Phase 2: Medium (3-5 days)
- Phase 3: Medium-High (4-6 days)
- Phase 4: Low (1-2 days)

## Critical Notes

### v3 Iteration Mode
Current API already supports iterative calls — no code changes needed for Phase 2.

### Orchestrator Invocation
Python function call (Option A) recommended for Phase 2. CLI subprocess (Option B) adds overhead but is cleaner.

### KB Retrieval Strategy
Query by: build_system, manifest_keys, error_pattern, group_id  
Ranking: exact tag (+10) > partial (+5) > group (+3) > text similarity (0-5)

## Why This Matters

**Reason:** Validates that v4 is an incremental evolution, not a rewrite — most infrastructure already exists and is battle-tested through experiments #001-#028.

**How to apply:** Builder should reuse existing functions wherever possible, focusing new code on the 15% gap (orchestrator + KB). No breaking changes to v3.
