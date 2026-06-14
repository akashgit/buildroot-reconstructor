# Strategist Agent Output

- **timestamp:** 2026-06-14T00:45:40Z
- **exit_code:** 0

---

Strategy written to `.factory/strategy/current.md`.

**Summary:** Single hypothesis (targeted mode) — **H1: Replace raw API calls with Claude Code subprocess agents** (issue #19, EXPLORE, growth dimension: capability_surface).

The hypothesis covers all 4 deliverables from the issue: Inner Builder, Outer Builder, and Outer Strategist replacements plus the new Outer Researcher agent. It creates a shared `claude_runner.py` utility, replaces the 2 `AnthropicVertex` call sites (builder.py:86, outer_loop.py:376) and the hardcoded dict in outer_strategist.py:148, adds outer_researcher.py, updates guards.py mutable surfaces, and mandates E2E verification on commons-lang3 + the 3-package smoke test. Current baseline: composite 0.844 (tests=1.0, lint=1.0, type_check=0.2, coverage=1.0, observability=0.33).
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
