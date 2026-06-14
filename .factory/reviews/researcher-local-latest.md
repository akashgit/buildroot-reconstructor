# Researcher Agent Output

- **timestamp:** 2026-06-14T00:37:26Z
- **exit_code:** 0

---

Research complete. Written to `.factory/strategy/research-local.md`.

**Key findings:**

1. **Three AnthropicVertex call sites** to replace: Inner Builder (`builder.py:92-111`), Outer Builder (`outer_loop.py:420-426`), and the Outer Strategist (`outer_strategist.py:148-183` — a hardcoded dict, not even an LLM call).

2. **No existing tests mock AnthropicVertex** — all builder tests cover utility functions only (`sanitize_gha_expressions`, `_format_dead_ends`). The replacement should break zero tests.

3. **Factory's Claude Code runner** (`factory/runners/claude.py`) provides the exact subprocess pattern: `claude --append-system-prompt-file <file> -p <task> --output-format json --dangerously-skip-permissions`.

4. **meta_guidance flows** `read_patterns()` → `run_batch()` → `run_inner_loop()` → `Builder.__init__()` → prepended to SYSTEM_PROMPT. Must be preserved in the temp prompt file.

5. **The 200-line file cap** in `_outer_builder_implement()` (line 456) is the most concrete limitation — Claude Code's Edit tool eliminates this entirely.

6. **New file needed:** `outer_researcher.py` — must be added to `MUTABLE_SURFACES` in `guards.py`.

7. **Current eval baseline:** tests=1.0, lint=1.0, 401 tests pass, 73% coverage. No regression expected from this change.
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
