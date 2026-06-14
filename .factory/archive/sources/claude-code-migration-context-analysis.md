---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-19
source: factory-archivist
date: 2026-06-13
---

# Context Analysis: Claude Code Agent Migration Architecture

## Summary

Architectural analysis mapping what experiment #007 built vs what needs to change, covering all 8 agent modules, the 4 agents requiring migration, the new Outer Researcher agent, risk assessment, test strategy, and recommended implementation phasing.

## Key Findings

### Module Migration Map (8 modules)
| Module | Migration Needed | Reason |
|--------|-----------------|--------|
| `builder.py` | YES | Replace AnthropicVertex with Claude Code subprocess |
| `outer_loop.py` (OuterBuilder) | YES | Replace AnthropicVertex, remove 200-line cap |
| `outer_strategist.py` | YES | Replace hardcoded dict with LLM-powered hypothesis generation |
| `outer_researcher.py` (NEW) | NEW | Web research between Failure Analyst and Strategist |
| `observer.py` | No | Wraps BuildrootOrchestrator, no LLM |
| `evaluator.py` | No | FIXED_SURFACE, no LLM |
| `analyzer.py` | No | Regex classification |
| `failure_analyst.py` | No | Python aggregation |

### Outer Builder Design Decision
Two options for how the Claude Code agent returns changes:
- **Option A**: Agent edits files in-place via Edit tool, outer loop captures diff via `git diff`
- **Option B**: Agent returns `{file_path: new_content}` dict, preserving existing `_apply_changes` flow
- **Recommendation**: Option A — more natural for Claude Code, removes 200-line cap, existing `_get_git_diff()` and `_revert_changes()` already use git

### New Outer Researcher Integration Point
Slots between steps 2 and 3 of `run_intelligent_outer_loop()`:
```
analyze_batch() → [NEW: outer_researcher_research()] → propose_hypothesis()
```
Research report feeds into Strategist as additional context for hypothesis generation.

### Risk Assessment (8 risks identified)
1. **Subprocess reliability**: Timeouts (120-300s per agent), crash recovery
2. **Output parsing**: Containerfile extraction, JSON hypothesis validation
3. **Test breakage**: 481 tests, but no AnthropicVertex mocks to break
4. **Outer Builder flow change**: Partial edit crash risk → save originals or use git stash
5. **Cost/latency**: ~45 subprocess spawns per batch, +5-10s each = ~7.5 min overhead (within 60 min budget)
6. **Model configuration**: Vertex AI env vars must be set for Claude Code
7. **Permission bypass safety**: Guards + git revert are the safety layer, not permission prompts
8. **Structured output**: Strategist needs valid `CodeChangeHypothesis` JSON — fallback to hardcoded dict

### Recommended Implementation Order
1. **Phase 1: Inner Builder** — highest impact, most isolated (`builder.py` only)
2. **Phase 2: Outer Strategist** — replaces hardcoded dict, unlocks novel hypotheses
3. **Phase 3: Outer Researcher** — new module, no existing code to break
4. **Phase 4: Outer Builder** — most complex change, depends on other 3 being stable
5. **Phase 5: E2E verification** — full loop validation

### Test Strategy
- **Unit**: Mock `subprocess.run`, verify command construction and output parsing
- **Integration**: Real subprocess with mocked LLM responses
- **E2E**: Real Claude Code on 1 package (commons-lang3), full cycle on 3+ packages
- **Regression**: All 481 tests must pass, eval score >= 0.55

### Files Requiring MUTABLE_SURFACES Update
- `src/buildroot/agent/outer_researcher.py` (new)
- `src/buildroot/agent/claude_runner.py` (new shared utility)
- `factory.md` Mutable Surfaces section must match

## Relevance to Strategy

This analysis provides the complete implementation roadmap. The phased approach minimizes integration risk by starting with the most isolated change (Inner Builder) and ending with the riskiest (Outer Builder). The shared `claude_runner.py` utility prevents code duplication across 4 agents.
