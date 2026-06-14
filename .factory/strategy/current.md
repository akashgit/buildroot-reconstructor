## Strategy — 2026-06-13

### Design Space
| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | Inner loop, outer loop, failure analyst, strategist, guards all built |
| Bug fixes | 3 | 5 code review fixes on PR #18, J-score epsilon, diff format fixes |
| Instrumentation | 1 | 100 log statements across 220 functions (15% coverage), structured=no |
| Flow changes | 2 | Outer loop orchestrator exists but uses raw API calls + hardcoded dict |
| New agents | 1 | No Claude Code agents yet — all agents are raw AnthropicVertex one-shots |
| Prompt engineering | 2 | Builder system prompt exists, meta_guidance injection works |
| Eval improvements | 2 | 5-dimension eval in place, type_check at 0.2 |
| Knowledge management | 2 | KB directory + patterns.md exist, strategy archive in place |
| Infrastructure | 1 | No CI, no automated E2E, rh-h100-01 SSH builds only |
| Operational execution | 1 | Smoke test on 3 packages ran once; no systematic L3/L4 runs |
| Self-evolution | 0 | Outer loop code mutation exists but is a single-shot text completion |

**Underserved:** New agents (1), Infrastructure (1), Self-evolution (0)

### Observations
- Current composite score: 0.844
- Weakest eval dimension: type_check (0.20, weight=0.125)
- Second weakest: observability (0.33, weight=0.083)
- Strongest: tests (1.0), lint (1.0), coverage (1.0)
- No experiments recorded yet — this is the first hypothesis cycle
- Pattern: The project has a functional inner+outer loop but every LLM-calling agent uses `AnthropicVertex` single-shot completions with no tools. This is the single largest architectural bottleneck — agents cannot iterate, cannot read files, cannot search the web, cannot debug build errors. Issue #19 is the highest-leverage change available.

### Call Sites to Replace

| Agent | File | Line | Current | Problem |
|---|---|---|---|---|
| Inner Builder | `builder.py:86-111` | `AnthropicVertex.messages.create()` | Single-shot text completion, no tools, no iteration |
| Outer Builder | `outer_loop.py:376-435` | `AnthropicVertex.messages.create()` | 200-line file cap, full-file rewrite, no test verification |
| Outer Strategist | `outer_strategist.py:148-183` | Hardcoded Python dict | Not even an LLM call — 4 canned hypotheses only |
| Outer Researcher | Does not exist | N/A | No web research before hypothesis generation |

### Hypotheses

#### H1: Replace raw API calls with Claude Code subprocess agents across all loops
- **Category:** EXPLORE
- **Type:** code
- **Backlog item:** Replace raw API calls with Claude Code agents across inner and outer loops (issue #19)
- **Growth dimension:** capability_surface
- **Addresses:** #19
- **What:** Create a shared `claude_runner.py` utility module that wraps `subprocess.run(["claude", ...])` with structured output parsing, error handling, and configurable per-agent options (model, turn limits, allowed tools). Then replace the 3 existing raw API call sites and add 1 new agent:
  1. **Inner Builder** (`builder.py`): Replace `AnthropicVertex.messages.create()` at line 86-111 with `claude -p` subprocess. System prompt file includes current Containerfile, build error, dead-end registry, spec, meta_guidance. Three modes (refine/explore/fresh_start) become task description variations. Agent gets Read/Edit/Bash/WebSearch tools.
  2. **Outer Builder** (`outer_loop.py:372-435`): Replace `OuterBuilder` class with `claude -p` subprocess. Remove 200-line file cap — Edit tool handles any file size. System prompt includes hypothesis, target files, error context.
  3. **Outer Strategist** (`outer_strategist.py:148-183`): Replace `propose_hypothesis()` hardcoded dict with `claude -p --json-schema` subprocess. Agent receives failure analysis, KB patterns, strategy archive (recent J scores + verdicts), mutable surfaces list. Outputs structured `CodeChangeHypothesis`.
  4. **Outer Researcher** (NEW `outer_researcher.py`): Claude Code agent between Failure Analyst and Strategist. Reads failure analysis + KB, does web research on dominant failure patterns, outputs research report fed to Strategist.
  5. **Update `guards.py`**: Add `outer_researcher.py` and `claude_runner.py` to `MUTABLE_SURFACES`.
  6. **Tests**: Unit tests mocking `subprocess.run` for each agent. Integration test verifying prompt construction and output parsing.
  7. **E2E**: Run inner loop on 1 package (commons-lang3) with Claude Code Builder. Run full outer loop cycle on smoke test (3 packages).
- **Why:** Every agent is currently a single-shot text completion with no tools. The Claude Code subprocess pattern gives each agent full tool access (Read, Edit, Bash, WebSearch, grep, git), iterative debugging capability, and access to the full codebase. The CEO's research review confirms 3 researchers independently validated the approach — all call sites identified, no test breakage expected, per-agent config specs ready. The external researcher provided the complete `spawn_claude_agent()` reference implementation with `--append-system-prompt-file`, `--json-schema`, and `--bare` flags. This is the single highest-leverage change: it transforms the system from one-shot text generation to fully agentic code modification.
- **Expected impact:** capability_surface +0.15 (new agent + upgraded agents), tests maintained at 1.0 (mock subprocess in unit tests + E2E passes), lint maintained at 1.0. No direct impact on type_check or observability this cycle — those are separate concerns. The real impact is on the research metric (solve_rate) which should improve significantly when the Inner Builder can iterate and debug, but that requires an actual batch run on rh-h100-01 to measure.
- **Priority:** high

### Anti-patterns to Avoid
- **Don't do full-file rewrites via API**: The current Outer Builder reads the entire file, sends it to the LLM, and replaces the whole file with the response. This is fragile (small context window errors corrupt the whole file) and caps at 200 lines. Claude Code's Edit tool makes surgical changes.
- **Don't hardcode hypotheses**: The current Outer Strategist is a Python dict mapping 4 error classes to canned hypotheses. Any failure mode not in the dict gets a generic fallback. An LLM agent can reason about novel failure patterns.
- **Don't remove the AnthropicVertex dependency entirely yet**: Other parts of the codebase may import it. Remove only the specific call sites in builder.py and outer_loop.py. The package can be removed from pyproject.toml in a future cleanup.
- **Don't skip E2E verification**: Issue #19 explicitly mandates E2E. Unit tests with mocked subprocess are necessary but insufficient — the full pipeline (inner loop on 1 package, outer loop cycle on 3 packages) must run.
- **Don't modify fixed surfaces**: evaluator.py, jar_comparator.py, eval/score.py, packages_smoke.txt are locked. The claude_runner.py is a new file under src/buildroot/agent/ which is within modifiable scope.

### New Backlog Items
(none — targeted mode, no new items)
