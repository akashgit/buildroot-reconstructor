---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-19
source: factory-archivist
date: 2026-06-13
---

# Local Analysis: Claude Code Agent Migration (Issue #19)

## Summary

Comprehensive local codebase analysis identifying all AnthropicVertex call sites, data flows, test coverage gaps, and mutable/fixed surface constraints for migrating 3 existing agents + 1 new agent to Claude Code subprocess spawning.

## Key Findings

### AnthropicVertex Call Sites (3 total)
1. **Inner Builder** (`builder.py:86-111`): `AnthropicVertex.messages.create()` with `max_tokens=4096`, single-shot text completion. Three mode methods (`refine`, `explore`, `fresh_start`) all call `_call_llm()`.
2. **Outer Builder** (`outer_loop.py:372-472`): Same pattern with `max_tokens=8192`, full-file replacement model with 200-line file cap at line 456.
3. **Outer Strategist** (`outer_strategist.py:148-263`): NOT an LLM call — pure Python dict mapping 4 hardcoded error classes to canned `CodeChangeHypothesis` objects.

### Critical Data Flow: meta_guidance
`knowledge_base.py:read_patterns()` → `run_intelligent_outer_loop()` → `run_batch()` → `run_inner_loop()` → `Builder.__init__(meta_guidance=...)` → `Builder._call_llm()` prepends to SYSTEM_PROMPT. Must be preserved in Claude Code version via `--append-system-prompt-file`.

### Test Coverage Analysis
- **401 tests passing**, 73% coverage
- **No existing tests mock AnthropicVertex** — all LLM-calling code paths are untested
- `test_agent_builder.py` (10 tests): only covers `sanitize_gha_expressions()` and `_format_dead_ends()`
- `test_outer_loop_v2.py` (12 tests): mocks `run_inner_loop`, not `Builder` directly
- `test_outer_strategist.py` (16 tests): tests pure Python logic only
- **Conclusion**: Replacing AnthropicVertex with subprocess calls should NOT break any tests

### Mutable/Fixed Surface Constraints
- Primary targets (`builder.py`, `outer_loop.py`, `outer_strategist.py`) are all in MUTABLE_SURFACES
- New files (`outer_researcher.py`, `claude_runner.py`) need to be added to `guards.py:MUTABLE_SURFACES`
- `evaluator.py`, `eval/score.py`, `jar_comparator.py`, `maven_central.py` are FIXED — cannot modify

### Current Limitations Addressed by Migration
- One-shot text completion — can't iterate on errors
- No tool access (can't read POM files, search Maven docs)
- Full Containerfile replacement — no surgical edits
- 200-line file cap for outer builder
- Only 4 hardcoded error classes in strategist
- No research step between failure analysis and hypothesis generation

### Eval Baseline
- Composite: passing (tests=1.0, lint=1.0, type_check=0.2, coverage=1.0, observability~0.58)
- Score: 0.8439 post experiment #007

## Relevance to Strategy

This analysis confirms the migration is low-risk for test regression (no AnthropicVertex mocks to break) and high-impact for capability (tool access, iteration, web research). The meta_guidance flow is the main integration point that must be preserved exactly.
