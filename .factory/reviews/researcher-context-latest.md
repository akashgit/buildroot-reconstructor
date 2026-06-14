# Researcher Agent Output

- **timestamp:** 2026-06-14T00:33:22Z
- **exit_code:** 0

---

Research context written to `.factory/strategy/research-context.md`. Here's what I found:

**What exists today**: Experiment 7 built the full outer loop (failure analyst, guards, J-score strategy archive, KB injection) but all 3 LLM-using agents are single-shot `AnthropicVertex` API calls with no tools. The strategist is a hardcoded Python dict mapping 4 error classes to canned hypotheses.

**What needs to change**:
- **Inner Builder** (`builder.py`): Replace `_call_llm()` with Claude Code subprocess. 3 methods (refine/explore/fresh_start) become different task descriptions. Interface to `loop.py` stays the same.
- **Outer Builder** (`outer_loop.py:OuterBuilder`): Replace with Claude Code that uses Edit tool. Removes 200-line cap. Changes the `_apply_changes()` flow since the agent edits files directly.
- **Outer Strategist** (`outer_strategist.py:propose_hypothesis()`): Replace hardcoded dict with Claude Code agent that returns `CodeChangeHypothesis` JSON. Data structures unchanged.
- **Outer Researcher** (new `outer_researcher.py`): Goes between failure analyst and strategist. WebSearch for failure pattern solutions.

**Biggest risks**: Subprocess reliability/timeout, structured output parsing from strategist, Outer Builder flow change (direct edit vs. return-content pattern), and Vertex AI billing configuration for the `claude` CLI. The research doc covers mitigations for each.

**Test strategy**: Mock `subprocess.run` for unit tests, real subprocess with mocked LLM for integration, and mandatory E2E on 1 package (inner) + 3 packages (outer). All 481 existing tests must continue passing.
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
