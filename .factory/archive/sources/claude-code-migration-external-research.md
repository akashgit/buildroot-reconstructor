---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-19
source: factory-archivist
date: 2026-06-13
---

# External Research: Claude Code Subprocess Spawning Patterns

## Summary

Comprehensive CLI reference and Python implementation patterns for spawning Claude Code agents via `claude -p` subprocess. Covers system prompt customization, structured output, permission modes, cost control, Vertex AI integration, and the Agent SDK alternative.

## Key Findings

### Core CLI Pattern
```
claude --bare -p "task" --append-system-prompt-file ./prompt.txt --output-format json --model claude-opus-4-6 --max-turns 30 --max-budget-usd 5.00 --dangerously-skip-permissions
```
- 3-5 second startup overhead per subprocess (Node.js startup, CLI init, auth handshake)
- Piped stdin capped at 10MB
- Exit code 0 on success, 1 on error

### System Prompt Strategy
- **Use `--append-system-prompt-file`** (not `--system-prompt`) to preserve default tool guidance, safety instructions, and coding conventions
- Write per-agent prompt to temp file, include agent role + constraints + context + expected output format
- Combined with `--bare` reduces system setup from ~50K tokens to ~10-15K per invocation

### Structured Output for Strategist
- `--json-schema` flag forces validated structured output
- Response includes `structured_output` field (validated object) alongside `result` (text)
- Not constrained generation — model produces JSON, post-hoc validated
- Ideal for `CodeChangeHypothesis` (5 fields, easy to validate)

### Bare Mode Benefits
- `--bare` skips hooks, skills, plugins, MCP servers, auto memory, CLAUDE.md auto-discovery
- Makes invocations deterministic — no ambient state
- Recommended for scripted/SDK calls
- Caveat: skips OAuth/keychain; auth must come from env vars or `--settings`

### Reference Implementation: `spawn_claude_agent()`
Complete Python function provided with:
- Temp file management for system prompts
- `subprocess.run` with timeout and error handling
- JSON parsing with fallback
- Cleanup in `finally` block
- Recommended as shared utility in `claude_runner.py`

### Per-Agent Configurations
| Agent | max-turns | max-budget-usd | timeout | Tools |
|-------|-----------|----------------|---------|-------|
| Inner Builder | 30 | $5.00 | 600s | Read, Edit, Bash, WebSearch |
| Outer Builder | 30 | $5.00 | 600s | Read, Edit, Bash |
| Outer Strategist | 10 | $2.00 | 300s | Read, WebSearch |
| Outer Researcher | 20 | $3.00 | 600s | Read, WebSearch, Bash |

### Vertex AI Integration
Required env vars: `CLAUDE_CODE_USE_VERTEX=1`, `ANTHROPIC_VERTEX_REGION=us-east5`, `ANTHROPIC_VERTEX_PROJECT_ID=itpc-gcp-ai-eng-claude`. Alternative: `--settings` JSON flag.

### Agent SDK vs Subprocess
Recommendation: **Use `subprocess.run` + `claude -p`** over `claude-agent-sdk` Python package. Rationale: simpler, more debuggable, supports structured output via `--json-schema`, avoids async complexity. SDK advantage (bidirectional streaming) not needed for batch pipeline.

## Sources
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless)
- [CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Bare mode documentation](https://code.claude.com/docs/en/headless#start-faster-with-bare-mode)
- [Permission modes](https://code.claude.com/docs/en/permission-modes)
- [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python)
- [Token Cost Analysis](https://dev.to/jungjaehoon/why-claude-code-subagents-waste-50k-tokens-per-turn-and-how-to-fix-it-41ma)
