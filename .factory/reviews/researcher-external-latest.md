# Researcher Agent Output

- **timestamp:** 2026-06-14T00:36:01Z
- **exit_code:** 0

---

Research complete. Written to `.factory/strategy/research-external.md` with 15 sections covering:

1. **Core `claude -p` pattern** — exact flags, behaviors, startup overhead (3-5s)
2. **System prompt customization** — recommends `--append-system-prompt-file` to preserve default tool guidance
3. **Structured output** — `--json-schema` for the Outer Strategist's `CodeChangeHypothesis`; plain `--output-format json` for Builder/Researcher
4. **Bare mode** — `--bare` reduces token overhead from ~50K to ~10-15K per invocation
5. **Python subprocess pattern** — complete `spawn_claude_agent()` reference implementation with timeout, error handling, temp file management
6. **Permission modes** — `--dangerously-skip-permissions` with deny-rule safety net
7. **Cost/turn limits** — per-agent recommended settings (Inner Builder: 30 turns/$5, Strategist: 10 turns/$2)
8. **Vertex AI integration** — env vars (`CLAUDE_CODE_USE_VERTEX`, `ANTHROPIC_VERTEX_REGION`, etc.)
9. **Agent SDK vs subprocess** — recommends subprocess for debuggability and structured output support
10. **Error handling patterns** — exit codes, JSON-level errors, timeout handling, common failure modes
11. **Prior archive knowledge** — 6 relevant papers/sources already in the archive that validate the approach
12. **Per-agent implementation specs** — exact configurations for all 4 agents

Key finding: a shared `claude_runner.py` utility module should handle subprocess lifecycle for all agents, with per-agent configuration for system prompts, schemas, turn limits, and budgets.
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
