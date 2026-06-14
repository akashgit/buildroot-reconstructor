# Local Research — Replace Raw API Calls with Claude Code Agents (Issue #19)

## 1. Current Implementation of AnthropicVertex Calls

### 1.1 Inner Builder (`builder.py`)

**Location:** `src/buildroot/agent/builder.py:86-111`

The `Builder` class creates an `AnthropicVertex` client directly:
```python
self._client = AnthropicVertex(region="us-east5", project_id="itpc-gcp-ai-eng-claude")
```

**`_call_llm()` (line 92-111):** Single-shot `messages.create()` with `max_tokens=4096`. Returns raw text, strips markdown code fences manually. No tools, no iteration, no file reading.

**Three mode methods all call `_call_llm()`:**
- `refine()` (line 113-143) — exploit mode, targeted fix with error + dead-ends + spec
- `explore()` (line 145-179) — different approach, explicitly tells LLM to change strategy
- `fresh_start()` (line 181-201) — regenerate from metadata only, ignores prior attempts

**Key constraint:** `meta_guidance` from the knowledge base is prepended to SYSTEM_PROMPT at line 94-95. This flow must be preserved in the Claude Code agent version.

**What's broken:**
- One-shot text completion — can't iterate on errors
- No tool access (can't read POM files, search Maven docs, check dependency versions)
- Output is full Containerfile replacement — no surgical edits
- `sanitize_gha_expressions()` post-processing needed because LLM can't be told to not use them reliably

### 1.2 Outer Builder (`outer_loop.py:372-472`)

**`OuterBuilder` class (line 372-435):** Same pattern — `AnthropicVertex` client, `messages.create()` with `max_tokens=8192`, manual code-fence stripping.

**`generate_change()` (line 381-435):** Takes hypothesis + file path + current source + error classes + archive entries. Feeds entire file content into prompt, asks for complete modified file back.

**`_outer_builder_implement()` (line 438-472):** Orchestrator function:
- Iterates `hypothesis.files_to_modify`
- **200-line file cap at line 456** — skips files >200 lines
- Creates `OuterBuilder()` for each call
- Returns `dict[str, str]` of `{file_path: new_content}`

**What's broken:**
- Full-file replacement model means it can't handle large files
- No ability to run tests or verify changes compile
- No iterative debugging — one-shot rewrite
- Each file modification is independent (can't see cross-file dependencies)

### 1.3 Outer Strategist (`outer_strategist.py:148-263`)

**`propose_hypothesis()` (line 148-183):** NOT an LLM call at all. Pure Python dict lookup:
- Checks archive for previously reverted strategies (line 159-161)
- On stagnation → `_propose_architectural_change()` (line 164)
- Iterates `analysis.error_frequencies`, skips exhausted/previously-tried classes (line 175-181)
- Calls `_propose_for_error_class()` which is a hardcoded `strategies` dict (line 192-228) mapping 4 known error classes to canned `CodeChangeHypothesis` objects

**What's broken:**
- Only knows 4 error classes: `compilation/jdk_mismatch`, `dependency_resolution/missing_artifact`, `build_tool/multi_module`, `plugin/configuration_error`
- Fallback for unknown errors is generic: "Address X failures" with first mutable surface (line 233-241)
- No reasoning, no web research, no access to knowledge base content
- Cannot discover novel strategies

### 1.4 Outer Researcher

**Does not exist.** The outer loop goes directly from `analyze_batch()` → `propose_hypothesis()` with no research step in between. The strategist is blind to external knowledge about failure patterns.

---

## 2. Factory Claude Code Subprocess Pattern

**Reference implementation:** `factory/runners/claude.py` (remote-factory repo)

### `ClaudeRunner.build_command()` (line 57-82)
```python
cmd = [
    "claude", "--append-system-prompt-file", prompt_file.name,
    "-p", request.task,
    "--output-format", "json",
]
if request.skip_permissions:
    cmd.append("--dangerously-skip-permissions")
if request.model:
    cmd.extend(["--model", request.model])
```

Key patterns:
1. **System prompt → temp file** via `--append-system-prompt-file`
2. **Task → `-p` flag** (single-shot headless mode)
3. **JSON output** via `--output-format json`
4. **Permissions bypass** via `--dangerously-skip-permissions`
5. **Model override** via `--model`
6. **Temp file cleanup** in `finally` block
7. **Result parsing:** JSON output contains `{result, usage, cost_usd, duration_ms, num_turns, model}`
8. **CWD control:** `subprocess.run(cmd, cwd=request.cwd)` — agent runs in the project directory

### Async subprocess execution
Uses `run_subprocess()` helper (imported from `_subprocess.py`) for non-blocking execution with timeout.

### What the buildroot project needs to adopt
- System prompt written to temp file (contains: KB patterns, error context, dead-end registry, spec metadata, mutable surfaces list)
- Task string describes the specific mutation goal (refine/explore/fresh_start for inner; hypothesis implementation for outer)
- Output parsed from JSON `result` field
- CWD set to project root so the agent can read any file
- `--dangerously-skip-permissions` for headless operation
- Model set to `claude-opus-4-6`

---

## 3. Models and Data Structures

### Inner Loop (`models.py`, `loop.py`)

**`BuildAttempt`** — tracks each iteration: containerfile, reward, level_reached, error_class, build_log_summary, diff_summary, fix_applied, q_value, n_expansions, timestamp.

**`DeadEndEntry`** — exhausted approach: error_class, approach, failure_count, threshold (default 2), examples. `is_exhausted` when failure_count >= threshold.

**`EvalResult`** — 4-level scoring: l1_parse (0.05), l2_build (0.10), l3_command (0.35), l4_match (0.50). Total reward = weighted sum. FIXED — cannot change.

**`ProgressSignal`** — AdaEvolve G_t exponential-decay for mode switching. exploit (G_t > tau_m=0.12), explore (G_t > tau_s=0.02), meta_shift (G_t ≤ tau_s).

**`LoopResult`** — aggregate: coordinate, status, best_reward, best_attempt, attempts list, dead_ends list, iterations, elapsed_seconds, error_message.

### Outer Loop (`outer_strategist.py`)

**`CodeChangeHypothesis`** — target_error_class, files_to_modify, expected_impact, rationale, priority. The Strategist Claude Code agent must produce this as structured JSON output.

**`StrategyScore`** — J(S) scoring per cycle: cycle, solve_rate_before, solve_rate_after, j_score, hypothesis, verdict.

**`StrategyArchive`** — list of StrategyScore, stagnation detection (3 consecutive J < 0.01), save/load to JSON.

**`FailureAnalysis`** — total/failed/solved packages, error_frequencies (list of ErrorClassFrequency), dominant_error_class, is_stagnant.

### Key data flow for Claude Code agent outputs

| Agent | Input | Expected Output | Format |
|-------|-------|-----------------|--------|
| Inner Builder | error, spec, dead_ends, meta_guidance, containerfile | New Containerfile text | Raw text (Containerfile content) |
| Outer Builder | hypothesis, target files | Modified file contents | Dict[str, str] — {file_path: content} |
| Outer Strategist | failure_analysis, archive, KB patterns | CodeChangeHypothesis | JSON matching dataclass schema |
| Outer Researcher (NEW) | failure_analysis, KB | Research report text | Markdown text appended to KB |

---

## 4. Current Test Coverage

### Test files and counts
| File | Tests | What it covers |
|------|-------|----------------|
| `test_agent_builder.py` | 10 | `sanitize_gha_expressions()`, `_format_dead_ends()` — NO tests for `_call_llm`, `refine`, `explore`, `fresh_start` |
| `test_outer_loop_v2.py` | 12 | `_load_packages`, `_apply_changes`, `_revert_changes`, `_get_git_diff`, `_save_package_results`, `run_batch`, `run_outer_loop` — tests mock `run_inner_loop` |
| `test_outer_strategist.py` | 16 | `compute_j_score`, `StrategyArchive`, `CodeChangeHypothesis`, `propose_hypothesis` — comprehensive coverage of the Python logic |
| `test_failure_analyst.py` | ~15 | `analyze_batch`, `_extract_dominant_error`, `_check_stagnation` |
| `test_guards.py` | ~20 | `check_surfaces`, `scan_leakage`, `check_monotonic`, `check_all` |
| `test_knowledge_base.py` | ~10 | `read_patterns`, `record_pattern`, `update_taxonomy` |

**Total:** 401 tests pass (eval dimension), 5023 LOC across all test files.

### Coverage gaps relevant to this change
1. **Builder LLM calls are NOT tested** — `test_agent_builder.py` only tests `sanitize_gha_expressions` and `_format_dead_ends`. The `Builder` class's `refine/explore/fresh_start` methods are untestable without mocking `AnthropicVertex`.
2. **OuterBuilder is NOT tested** — no tests for `OuterBuilder.generate_change()` or `_outer_builder_implement()`.
3. **Inner loop integration** (`test_outer_loop_v2.py`) mocks `run_inner_loop` — no test exercises Builder → Evaluator flow.
4. **`run_intelligent_outer_loop` has NO tests** — the full outer cycle is only exercised in E2E runs.

### Testing strategy for Claude Code replacement
- Tests that mock `AnthropicVertex` will need to mock `subprocess.run` instead
- The contract changes: instead of asserting on API call args, assert on CLI command construction
- `_outer_builder_implement()` tests should verify temp file creation/cleanup
- The Strategist's `propose_hypothesis()` will need new tests since it changes from pure Python to subprocess call
- Existing tests for `sanitize_gha_expressions`, dead-end formatting, and helper functions remain unchanged

---

## 5. Mutable and Fixed Surfaces

### From `factory.md`
**Mutable Surfaces:**
- `src/buildroot/agent/builder.py` ← PRIMARY target
- `src/buildroot/agent/analyzer.py`
- `src/buildroot/agent/loop.py` ← needs update (Builder instantiation)
- `src/buildroot/agent/observer.py`
- `src/buildroot/agent/outer_loop.py` ← PRIMARY target (OuterBuilder)
- `src/buildroot/agent/models.py`
- `src/buildroot/templates/*.j2`

**Fixed Surfaces:**
- `src/buildroot/agent/evaluator.py` — CANNOT modify
- `eval/score.py` — CANNOT modify
- `results/packages_smoke.txt` — CANNOT modify
- `src/buildroot/utils/jar_comparator.py` — CANNOT modify
- `src/buildroot/utils/maven_central.py` — CANNOT modify

### From `guards.py`
`MUTABLE_SURFACES` frozenset (line 12-26) includes all agent files + CLI command. This set needs to be updated if new files are added (e.g., `outer_researcher.py`).

`MUTABLE_GLOBS` (line 28-33) includes `src/buildroot/agent/knowledge/`, `src/buildroot/templates/`, `tests/`, `results/`.

### Implications for the change
1. The primary targets (`builder.py`, `outer_loop.py`, `outer_strategist.py`) are all in MUTABLE_SURFACES — good.
2. If we add `outer_researcher.py`, it falls under the `src/buildroot/agent/` prefix which isn't in MUTABLE_GLOBS. Need to either add it to `MUTABLE_SURFACES` in `guards.py` or accept that the outer loop doesn't self-modify the researcher.
3. `loop.py` is mutable — we can change how `Builder` is instantiated there.
4. `knowledge_base.py` and its directory are mutable via MUTABLE_GLOBS.

---

## 6. meta_guidance Flow: KB → Builder

### Current flow
1. `knowledge_base.py:read_patterns()` reads `knowledge/patterns.md`, extracts "General Patterns" section
2. `outer_loop.py:run_intelligent_outer_loop()` calls `read_patterns()` at line 183
3. Passes `kb_patterns` to `run_batch()` as `meta_guidance` at line 190
4. `run_batch()` passes `meta_guidance` to `run_inner_loop()` at line 103
5. `loop.py:run_inner_loop()` passes `meta_guidance` to `Builder(model=model, meta_guidance=meta_guidance)` at line 56
6. `builder.py:Builder.__init__()` stores `self._meta_guidance` at line 90
7. `builder.py:Builder._call_llm()` prepends meta_guidance to SYSTEM_PROMPT at line 94-95

### Required preservation in Claude Code version
The meta_guidance content must be included in the system prompt file that `--append-system-prompt-file` points to. The flow path needs to be:
1. `read_patterns()` → string content (unchanged)
2. `run_batch()` → `run_inner_loop()` → meta_guidance parameter (unchanged)
3. `run_inner_loop()` → write meta_guidance into the temp prompt file before spawning Claude Code
4. Claude Code agent reads the system prompt with KB patterns as context

This is actually cleaner with Claude Code because the agent can also directly read `knowledge/patterns.md` and other KB files if needed.

---

## 7. Eval Score Baseline

**Current composite: passing** (tests=1.0, lint=1.0, type_check=0.2, coverage=1.0, observability≈0.58)

- 401 tests pass (one test_level1 failure in spring-security-core JDK version, excluded from eval)
- Lint: clean
- Mypy: 10 errors in 6 files (most in evaluator.py which is FIXED)
- Coverage: 73%

### Regression risk
The main risk is breaking existing tests that mock `AnthropicVertex`. However, reviewing the tests:
- `test_agent_builder.py` does NOT mock or call `Builder` — only tests utility functions
- `test_outer_loop_v2.py` mocks `run_inner_loop`, not `Builder` directly
- `test_outer_strategist.py` tests pure Python logic, not LLM calls

**Conclusion:** No existing tests mock `AnthropicVertex`, so replacing it with subprocess calls should NOT break any tests. The untested LLM paths are the ones being replaced.

---

## 8. Architecture Summary & Implementation Considerations

### Subprocess wrapper needed
Create a lightweight `_run_claude_agent()` helper (in `builder.py` or a shared module) that:
1. Writes system prompt to temp file
2. Builds `claude -p ... --append-system-prompt-file ... --output-format json --dangerously-skip-permissions` command
3. Runs subprocess with timeout
4. Parses JSON output → extracts `result` field
5. Cleans up temp files
6. Returns the agent's text output

### Inner Builder transformation
- `Builder.__init__()` no longer needs `AnthropicVertex` client — just stores model name + meta_guidance
- `_call_llm()` → `_run_claude_agent()` with system prompt = meta_guidance + SYSTEM_PROMPT
- Three modes (refine/explore/fresh_start) become different task descriptions, not separate code paths (or keep as separate methods with different task prompts)
- Output still goes through `sanitize_gha_expressions()` post-processing
- `loop.py` changes minimally — Builder constructor signature stays the same

### Outer Builder transformation
- `OuterBuilder` class → Claude Code subprocess
- Remove 200-line file cap — agent uses Edit tool for surgical changes
- Agent runs in project root CWD so it can read target files directly
- System prompt includes: hypothesis details, error classes, archive context, mutable surfaces
- Task prompt tells agent which files to modify and what to change
- Output: agent writes files directly (no need for `_apply_changes`), OR returns structured JSON with changes

**Design decision needed:** Should the Outer Builder agent:
(a) Write files directly (agent modifies on disk, outer loop checks diff), or
(b) Return modified file contents in structured output (current pattern preserved)?

Option (a) is more natural for Claude Code (it has Edit/Write tools) but requires the outer loop to use git diff to detect what changed. Option (b) preserves the existing `_apply_changes` / `_revert_changes` flow.

**Recommendation:** Option (a) — let the agent write directly. The outer loop already calls `_get_git_diff()` and `_revert_changes()` uses git. The agent can make surgical edits and the outer loop validates via guards.

### Outer Strategist transformation
- `propose_hypothesis()` → Claude Code agent with structured output
- System prompt: failure analysis data, archive state, KB patterns, mutable surfaces
- Task: "Analyze the failure patterns and propose a CodeChangeHypothesis"
- Agent outputs JSON matching `CodeChangeHypothesis.to_dict()` schema
- Parse JSON → construct `CodeChangeHypothesis` dataclass
- Keep `compute_j_score()`, `StrategyArchive`, `StrategyScore` unchanged (pure Python, no LLM)

### Outer Researcher (NEW)
- New module: `src/buildroot/agent/outer_researcher.py`
- Claude Code agent that runs between Failure Analyst and Strategist
- Input: failure analysis (dominant error classes, frequencies), KB content
- Agent uses web search to research solutions for dominant failure patterns
- Output: research report → written to KB or returned as context for Strategist
- Add to `MUTABLE_SURFACES` in `guards.py`

### `anthropic` dependency
After this change, the `anthropic` package import can be removed from `builder.py` and `outer_loop.py`. Check if it's used elsewhere before removing from `pyproject.toml`.

---

## 9. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Claude Code CLI not available on build hosts | Medium | Check `shutil.which("claude")` before spawning; fall back to error |
| Subprocess timeout on complex tasks | Medium | Set reasonable timeouts (inner: 300s, outer: 600s, strategist: 120s) |
| JSON parsing failures from Claude Code output | Low | Robust parsing with fallback; the factory runner handles this pattern |
| Agent writes to FIXED surfaces | Medium | Set CWD appropriately; include surface constraints in system prompt; guards still check post-hoc |
| meta_guidance not flowing through | Low | Include KB content directly in system prompt file; agent can also read KB files |
| Existing tests break | Very Low | No tests mock AnthropicVertex; all LLM-calling code paths are untested |
| Cost increase (Claude Code uses more tokens) | High | Each agent invocation includes full tool-use context; but the quality improvement justifies this |
| Wall clock time increase | High | Claude Code agents take longer than single API calls; acceptable per issue spec ("60 min is acceptable") |
