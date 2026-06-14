## CEO Review: Researcher Agent (3 parallel)

- **Verdict:** PROCEED
- **Rationale:** All 3 researchers delivered comprehensive, complementary analysis with zero overlap waste.
- **Issues found:** none

### Assessment

**Local researcher (research-local.md, 310 lines):**
- Correctly identified all 3 AnthropicVertex call sites: builder.py:92-111, outer_loop.py:420-426, outer_strategist.py:148-183
- Confirmed no existing tests mock AnthropicVertex, so replacement breaks zero tests
- Traced meta_guidance flow: read_patterns() → run_batch() → run_inner_loop() → Builder.__init__()
- Identified the 200-line file cap in _outer_builder_implement() line 456
- Flagged that outer_researcher.py needs to be added to MUTABLE_SURFACES in guards.py
- Current baseline: tests=1.0, lint=1.0, 401 tests, 73% coverage

**External researcher (research-external.md, 474 lines):**
- Full CLI flag reference for claude -p subprocess pattern
- --append-system-prompt-file recommendation (preserves default tool guidance)
- --json-schema for Strategist's CodeChangeHypothesis structured output
- --bare mode recommendation for faster startup, reduced token overhead
- Complete spawn_claude_agent() reference implementation with error handling
- Per-agent configuration specs (turn limits, budgets, allowed tools)
- Vertex AI env var configuration

**Context researcher (research-context.md, 318 lines):**
- Clear mapping of what experiment 7 built vs what needs to change
- Risk assessment: subprocess reliability, structured output parsing, Outer Builder flow change
- Test strategy: mock subprocess.run for unit tests, real subprocess for integration, mandatory E2E
- All 481 existing tests must continue passing

### Instructions for Strategist
- Use the claude_runner.py shared utility recommendation from external research
- Inner Builder must preserve the meta_guidance → system prompt flow
- Outer Builder flow change is the riskiest part — must handle direct file edit vs return-content pattern
- New outer_researcher.py must be added to guards.py MUTABLE_SURFACES
