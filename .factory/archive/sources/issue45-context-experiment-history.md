---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-45
source: factory-archivist
date: 2026-06-18
---

# Issue #45 Context Research: Experiment History & Architecture Constraints

## Project State

- Current score: 0.6086 (post exp #015)
- Agentic solve rate: 33.3% (1/3 packages)
- L4 solve rate: 22.6% (7/31 on 31-package benchmark)
- Current loop shape: AnalyzeAgent -> spec_overrides -> re-observe (established in exp #015)

## commons-lang3 Regression Timeline

| Experiment | Status | Detail |
|---|---|---|
| #005 | L1 (accuracy 0.325) | JDK version mismatch (21 vs 8) |
| #006 | **L4 SOLVED** (reward=1.0) | Solved in 1 iteration |
| #010 | L3 (improved from L1) | Experiment reverted due to other regressions |
| Post #013 | **L1 (broken)** | REPRODUCIBLE_FLAGS regression — hardcoded `1980-01-01T00:00:00Z` rejected by maven-jar-plugin:3.3.0 |

### Root Cause of Regression
`REPRODUCIBLE_FLAGS` in `containerfile.py:27-29` hardcodes `-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z`. This value falls outside maven-jar-plugin:3.3.0's valid ZIP date range (requires dates after `1980-01-01T00:00:02Z`). The AnalyzeAgent ran 3 iterations without diagnosing the root cause because:
1. No tools enabled (all disabled at `analyzer.py:732`)
2. Build log truncated by three cascading truncations (5000 -> 3000 -> 500 chars)
3. `build_remediation_context()` never called
4. `_add_reproducible_flags()` re-injects the flag on every re-render
5. Node agents never see the build error

## Prior Experiments Validating This Approach

| Exp | Key Finding | Relevance |
|---|---|---|
| #010 | AnalyzeAgent concept validated — worked when it fired; failure was early termination, not the agent | HIGH — confirms diagnostic loop direction |
| #012 | Elitist gate fixed early termination from #010; patience counter with checkpoint-and-restore | HIGH — prerequisite for iteration improvements to matter |
| #013 | Information flow improvements delivered +0.2900; error patterns, evaluator output, SOURCE_DATE_EPOCH | HIGH — same category of change as issue #45 |
| #015 | Builder removed, AnalyzeAgent expanded with 3-tier spec_overrides; current loop shape | HIGH — this is the architecture issue #45 modifies |

## Architectural Constraints

1. **Elitist gate** (exp #012, `loop.py:120/438`): Patience counter restores best containerfile after 2 regressions. Error tracking must not conflict.
2. **spec_overrides accumulation**: Overrides accumulate across iterations within a phase; `meta_shift` clears them. Error history should track across meta_shift boundary (not be cleared).
3. **AnalyzeAgent tools**: All tools disabled (`disallowed_tools` at line 732). Issue #45 injects better context into the prompt instead.
4. **Node agent cost**: $5/agent x 10+ agents per observation = $50+/observation. Error context should reduce wasted iterations, not add cost.

## SOURCE_DATE_EPOCH Value Discrepancy

| Location | Current Value | Meaning |
|---|---|---|
| Templates (all 4) | `SOURCE_DATE_EPOCH=0` | Unix epoch (1970-01-01), set by exp #13 |
| REPRODUCIBLE_FLAGS | `-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z` | Set by exp #13, rejected by maven-jar-plugin:3.3.0 |
| Issue #45 spec | Default to "946684800" (2000-01-01) | Conservative, within ZIP date range |

The `outputTimestamp` value `1980-01-01T00:00:00Z` is the root cause of the commons-lang3 regression. Fix should change to `2000-01-01T00:00:00Z`.

## Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Prompt size increase breaks AnalyzeAgent token budget | Medium | Truncate remediation_context to ~2000 chars |
| Node agents fixate on wrong-domain errors | Low | "If relevant to your domain" guard |
| SOURCE_DATE_EPOCH default change breaks packages | Low | `if not in` check preserves default |
| Conflict with elitist gate | None | Error history is append-only |

## Implementation Order (from spec)
```
[4] Track error_history/previous_progress
  -> [1] Wire up build_remediation_context()
    -> [3] Fix SOURCE_DATE_EPOCH template ordering
      -> [2] Pass build errors to node agents
        -> [5] Expand TemplateAgent fix vocabulary
          -> [6] Add timestamp error pattern
```

## Verification Plan
Re-run commons-lang3:3.14.0 with `--node-agents --max-iter 5`. Expected: reaches L3+ within 2 iterations (vs 3 wasted iterations before). Mandatory real E2E on rh-h100 nodes (SSH as `lab`).
