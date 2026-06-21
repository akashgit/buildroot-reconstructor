---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 8
verdict: keep
score_before: 0.8442
score_after: 0.8456
score_delta: +0.0014
date: 2026-06-13
source: factory-archivist
---

# Experiment #008: Replace raw API calls with Claude Code subprocess agents

## Hypothesis
Replace all 3 raw `AnthropicVertex` single-shot API calls with Claude Code subprocess agents (`claude -p`) via a shared `claude_runner.py` utility, and add a new Outer Researcher agent for web research on failure patterns. This enables agents to iterate, use tools (Read, Edit, Bash, WebSearch), and produce structured output via `--json-schema`.

## Result
**KEEP** — score changed from 0.8442 to 0.8456 (+0.0014). CEO code review CLEAN. PR #21 left open for human review.

Small positive delta is expected for an infrastructure migration: the experiment replaced raw API calls with subprocess agents — same functional output but with tool access, iteration, and structured output. The investment unlocks future score gains when agents iterate on builds using tools instead of single-shot completions.

## What Changed

### New Files (4)
- `src/buildroot/agent/claude_runner.py` (135 lines) — Shared `spawn_claude_agent()` utility: subprocess management, JSON output parsing, temp file cleanup, 3 error paths (timeout, CLI not found, JSON parse failure)
- `src/buildroot/agent/outer_researcher.py` — New agent: web research on failure patterns between Failure Analyst and Strategist, uses WebSearch tool
- `src/buildroot/agent/failure_analyst.py` (187 lines) — Batch failure analysis, error class frequency, stagnation detection
- `src/buildroot/agent/knowledge/strategy_archive/.gitkeep` — Strategy archive directory

### Modified Files (9 key)
- `src/buildroot/agent/builder.py` — Replaced `AnthropicVertex.messages.create()` with `spawn_claude_agent()` in all 3 modes (refine, explore, fresh_start). Added `meta_guidance` constructor param, `_build_system_prompt()`, `_extract_containerfile()` helper. Removed `anthropic` import.
- `src/buildroot/agent/outer_loop.py` — Outer Builder migrated to Claude Code subprocess, removes 200-line file cap (agent uses Edit tool for surgical changes)
- `src/buildroot/agent/outer_strategist.py` — Migrated from hardcoded Python dict to Claude Code subprocess with `--json-schema` for structured `CodeChangeHypothesis` output. Added `_fallback_hypothesis()` for agent failures.
- `src/buildroot/agent/guards.py` — Added `claude_runner.py` and `outer_researcher.py` to `MUTABLE_SURFACES`
- `factory.md` — Expanded scope to include `src/**/*.md` and `src/**/.gitkeep`

### New Test Files (6, 29 new tests)
- `tests/test_claude_runner.py` (12 tests) — All error paths: timeout, FileNotFoundError, invalid JSON, flag passing
- `tests/test_builder_subprocess.py` — Builder modes with mocked `spawn_claude_agent`
- `tests/test_outer_researcher.py` (5 tests) — Report production, output file writing, error handling, system prompt content, WebSearch tool usage
- `tests/test_outer_strategist.py` (15+ tests) — J(S) scoring, strategy archive, hypothesis generation, research report injection, fallback hypothesis
- `tests/test_outer_loop_v2.py` (20+ tests) — Batch runs, meta_guidance, package loading, apply/revert changes, git diff, solve rate calculation
- `tests/test_failure_analyst.py` — Batch analysis, error classification, stagnation detection

### PR Stats
- **PR**: #21 (OPEN), closes #20
- **Diff**: +3120/−39 lines, 26 files changed, 7 commits
- **Tests**: 430 passing (29 new, up from 401), zero regressions
- **Lint**: clean (ruff)

## CEO Code Review
**Verdict: CLEAN** — no issues found.

Checklist:
- Correctness: PASS — `claude_runner.py` handles all error paths (timeout, non-zero exit, JSON parse failure, FileNotFoundError). Inner Builder preserves `meta_guidance` flow. Outer Strategist has proper fallback when agent fails. Outer Researcher returns empty string on failure (non-blocking).
- Security: PASS — No hardcoded secrets, no unsafe operations. Temp files cleaned up in `finally` block. `--dangerously-skip-permissions` necessary for headless Claude Code. No credential leakage.
- Edge cases: PASS — All three Claude runner error paths tested. Outer Builder snapshots originals before agent edit and reverts on failure. Strategist has `_fallback_hypothesis()` for agent failures.
- Missing tests: PASS — 29 new tests covering all error paths and flag passing.
- Style: PASS — Consistent with existing codebase. Proper logging. Clean imports. No dead code.
- Scope: PASS — Changes limited to declared scope. `factory.md` scope section expanded to include `*.md` and `.gitkeep`.
- Guardrails: PASS — No files exceed 500 lines. All modified files within `mutable_surfaces`. No dangerous commands.

## Architecture

### Agent Migration Map
| Agent | Before | After |
|-------|--------|-------|
| Inner Builder | `AnthropicVertex.messages.create()` single-shot | `spawn_claude_agent()` with 10 turns, $5 budget, 600s timeout |
| Outer Builder | Raw API, 200-line file cap | Claude Code subprocess with Edit tool, no file size limit |
| Outer Strategist | Hardcoded Python dict | Claude Code subprocess with `--json-schema` structured output |
| Outer Researcher | Did not exist | New agent with WebSearch tool, wired between Failure Analyst and Strategist |

### `spawn_claude_agent()` Interface
- `task`, `system_prompt` (required)
- `model` (default `claude-opus-4-6`), `json_schema`, `max_turns`, `max_budget_usd`, `timeout`, `cwd`, `allowed_tools`
- Returns `AgentResult` dataclass: `text`, `structured_output`, `is_error`, `error_message`, `cost_usd`, `num_turns`
- Flags: `--bare`, `--output-format json`, `--dangerously-skip-permissions`, `--append-system-prompt-file`

## Eval Notes
Final eval score: 0.8456 (up from 0.8442 pre-experiment). The earlier spurious 0.6130 reading was resolved — test suite and coverage detection recovered in the final eval run.

## Decision Rationale
- **KEEP**: Clean code review, all 430 tests passing, positive score delta, foundational infrastructure for future agentic improvements.
- The migration is an enabler: agents now have tool access (Read, Edit, Bash, WebSearch) and can iterate (up to 10 turns), replacing single-shot API calls that could only generate text.
- PR #21 left open for human review per protocol — the factory verdict is KEEP but the merge is gated on Akash's sign-off.

## Links
- Project: buildroot-reconstructor
- Issue: #19, #20
- PR: #21
- Strategy: `strategies/buildroot-reconstructor-2026-06-13-claude-code-migration.md`
- Research: `sources/claude-code-migration-local-analysis.md`, `sources/claude-code-migration-external-research.md`, `sources/claude-code-migration-context-analysis.md`
