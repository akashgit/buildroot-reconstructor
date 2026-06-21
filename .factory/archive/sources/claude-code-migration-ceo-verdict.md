---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-19
source: factory-archivist
date: 2026-06-13
---

# CEO Verdict on Research Phase: Claude Code Agent Migration

## Summary

CEO reviewed all 3 parallel researcher outputs for issue #19 (Claude Code agent migration) and issued a **PROCEED** verdict with zero issues found.

## Verdict Details

- **Verdict**: PROCEED
- **Issues found**: None
- **Rationale**: All 3 researchers delivered comprehensive, complementary analysis with zero overlap waste

## Researcher Assessments

### Local Researcher (310 lines)
- Correctly identified all 3 AnthropicVertex call sites
- Confirmed no existing tests mock AnthropicVertex (zero test breakage risk)
- Traced meta_guidance flow end-to-end
- Identified 200-line file cap and MUTABLE_SURFACES update need
- Baseline: tests=1.0, lint=1.0, 401 tests, 73% coverage

### External Researcher (474 lines)
- Full CLI flag reference for `claude -p` subprocess pattern
- `--append-system-prompt-file` recommendation (preserves default tool guidance)
- `--json-schema` for Strategist's `CodeChangeHypothesis` structured output
- `--bare` mode for faster startup, reduced token overhead (~10-15K vs ~50K)
- Complete `spawn_claude_agent()` reference implementation
- Per-agent configuration specs (turn limits, budgets, allowed tools)
- Vertex AI env var configuration

### Context Researcher (318 lines)
- Clear mapping of experiment #007 state vs migration targets
- 8-risk assessment with mitigations
- Test strategy: mock subprocess for unit tests, real subprocess for integration, mandatory E2E
- All 481 existing tests must continue passing

## Instructions to Strategist
1. Use the `claude_runner.py` shared utility recommendation from external research
2. Inner Builder must preserve the `meta_guidance → system prompt` flow
3. Outer Builder flow change is the riskiest part — must handle direct file edit vs return-content pattern
4. New `outer_researcher.py` must be added to `guards.py` MUTABLE_SURFACES
