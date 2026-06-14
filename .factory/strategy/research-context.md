# Research Context: Claude Code Agent Migration (Issue #19)

## 1. What Experiment 7 Built and What Needs to Change

### Current Architecture (post-experiment 7)

The inner/outer loop is fully operational with 8 agent modules under `src/buildroot/agent/`:

| Module | Role | LLM Integration | Migration Needed |
|--------|------|-----------------|------------------|
| `builder.py` | Inner Builder | `AnthropicVertex.messages.create()` — single-shot text completion | **YES — replace with Claude Code subprocess** |
| `outer_loop.py` (OuterBuilder class) | Outer Builder | `AnthropicVertex.messages.create()` — single-shot full-file rewrite | **YES — replace with Claude Code subprocess** |
| `outer_strategist.py` (`propose_hypothesis()`) | Outer Strategist | No LLM — hardcoded dict mapping 4 error classes to canned hypotheses | **YES — replace with Claude Code subprocess** |
| `observer.py` | Observer | No LLM — wraps `BuildrootOrchestrator.reconstruct()` | No change |
| `evaluator.py` | Evaluator | No LLM — SSH podman build + 4-level scoring | No change (FIXED_SURFACE) |
| `analyzer.py` | Analyzer | Regex classification + optional LLM fallback | No change |
| `failure_analyst.py` | Failure Analyst | No LLM — Python aggregation | No change |
| `guards.py` | Guards | No LLM — Python enforcement | No change |

**New module needed**: `outer_researcher.py` — Claude Code agent for web research between Failure Analyst and Strategist.

### What the Current Code Does (details)

**Inner Builder** (`builder.py:80-201`):
- `Builder` class with `AnthropicVertex` client, 3 methods: `refine()`, `explore()`, `fresh_start()`
- Each method constructs a prompt string, calls `self._client.messages.create()`, strips markdown fences, returns raw Containerfile text
- `meta_guidance` from KB is prepended to `SYSTEM_PROMPT` in `_call_llm()`
- `sanitize_gha_expressions()` runs as post-processing on all LLM output
- Called from `loop.py:137-158` based on `mode` (exploit/explore/meta_shift)

**Outer Builder** (`outer_loop.py:372-472`):
- `OuterBuilder` class, same `AnthropicVertex` pattern
- `generate_change()` takes hypothesis + current source, returns complete modified file
- 200-line cap at `outer_loop.py:456-458` — skips files over 200 lines
- `_outer_builder_implement()` function iterates `hypothesis.files_to_modify`, reads each file, calls `generate_change()`, returns `{file_path: new_content}` dict
- Changes applied via `_apply_changes()` (full file write) and reverted via `_revert_changes()`

**Outer Strategist** (`outer_strategist.py:148-263`):
- `propose_hypothesis()` — pure Python, no LLM call
- 4 hardcoded strategies in `_propose_for_error_class()` lines 192-228: `compilation/jdk_mismatch`, `dependency_resolution/missing_artifact`, `build_tool/multi_module`, `plugin/configuration_error`
- Fallback: picks first mutable surface file for unknown error classes
- Stagnation path: `_propose_architectural_change()` returns generic "improve Builder prompts"
- `StrategyArchive`, `StrategyScore`, `compute_j_score()`, `CodeChangeHypothesis` — these data structures stay unchanged

### What the Outer Loop Orchestrator Does (`outer_loop.py:148-369`)

`run_intelligent_outer_loop()` runs cycles:
1. `run_batch()` — inner loop on all packages with KB-injected `meta_guidance`
2. `analyze_batch()` — failure analyst aggregation
3. `propose_hypothesis()` — strategist (currently hardcoded dict)
4. `_outer_builder_implement()` — outer builder (currently raw API)
5. `check_surfaces()` — surface guard
6. `_apply_changes()` — write new file content
7. `_get_git_diff()` — capture diff
8. `run_batch()` again — re-run with changes
9. `check_all()` — full guard chain
10. Verdict: keep (commit) or revert

**The new Outer Researcher slot goes between steps 2 and 3** — after failure analysis, before hypothesis generation.

## 2. Agents That Need Migration

### 2.1 Inner Builder → Claude Code Agent

**Current**: `Builder._call_llm()` at `builder.py:92-111` — single API call, returns raw text.

**Target**: Claude Code subprocess that:
- Receives the Containerfile path (writes it to a temp file for the agent to read/edit)
- Gets system prompt via `--append-system-prompt-file` with error context, dead-ends, spec metadata, meta_guidance
- Has access to Read/Edit/Write tools for surgical Containerfile fixes
- Has Bash access (could read POM files, check Maven docs)
- Has WebSearch for researching error patterns
- Returns the modified Containerfile content

**Key changes to `builder.py`**:
- Remove `AnthropicVertex` import and client initialization
- Remove `_call_llm()` method
- Replace `refine()`, `explore()`, `fresh_start()` to each:
  1. Write a system prompt file (combining SYSTEM_PROMPT + mode-specific context + meta_guidance)
  2. Write the current Containerfile to a temp file
  3. Construct a task description (what to fix, error details, dead-ends)
  4. Call `subprocess.run(["claude", "--append-system-prompt-file", prompt_file, "-p", task, "--output-format", "json", "--dangerously-skip-permissions"])`
  5. Parse the JSON output to extract the Containerfile content
  6. Run `sanitize_gha_expressions()` post-processing

**Integration point in `loop.py`**: No change needed — the loop calls `builder.refine()`, `builder.explore()`, `builder.fresh_start()` and gets back a string. The interface stays the same.

**Risk**: The three modes (refine/explore/fresh_start) could collapse into a single method with different task descriptions, as suggested in the issue spec. However, keeping them separate preserves the existing interface that `loop.py` depends on.

### 2.2 Outer Builder → Claude Code Agent

**Current**: `OuterBuilder.generate_change()` at `outer_loop.py:381-435` — single API call, full file replacement.

**Target**: Claude Code subprocess that:
- Receives hypothesis context via system prompt
- Has Read/Edit/Write to make surgical edits (no 200-line cap)
- Can run `pytest` and `ruff` to verify changes don't break tests
- Returns a confirmation of what changed (the changes are already on disk since the agent edits in-place)

**Key design decision**: The current flow has the OuterBuilder return `{file_path: new_content}` which gets applied via `_apply_changes()`. With Claude Code, the agent edits files directly via Edit tool. This changes the flow:
- Option A: Agent edits files in-place, `_outer_builder_implement()` captures the diff via `git diff` after the agent runs
- Option B: Agent runs in a git worktree, changes are extracted and applied to the main tree
- Option A is simpler and matches the factory pattern. The existing `_apply_changes()` / `_revert_changes()` pattern would change to `git stash` / `git stash pop` or `git checkout -- .` for revert.

**The 200-line cap at `outer_loop.py:456-458` gets removed** — the Edit tool handles any file size.

### 2.3 Outer Strategist → Claude Code Agent

**Current**: `propose_hypothesis()` at `outer_strategist.py:148-183` — Python dict lookup, no LLM.

**Target**: Claude Code subprocess that:
- Receives failure analysis, KB patterns, strategy archive (recent J scores + verdicts), mutable surfaces list
- Reasons about failure patterns and generates a `CodeChangeHypothesis`
- Can optionally do web research if the failure patterns are novel
- Returns structured JSON output matching `CodeChangeHypothesis` schema

**Key design decision**: The output must be a valid `CodeChangeHypothesis` JSON. The Claude Code agent needs structured output extraction. Options:
- Parse JSON from the agent's text output
- Use `--output-format json` and extract from the `result` field
- Have the agent write a hypothesis JSON file, then read it back

The data structures (`CodeChangeHypothesis`, `StrategyScore`, `StrategyArchive`, `compute_j_score`) remain unchanged — only `propose_hypothesis()` and the two `_propose_*` helper functions get replaced.

## 3. New Outer Researcher Agent

**Purpose**: Web research on failure patterns between Failure Analyst and Strategist.

**Input**:
- `FailureAnalysis` (dominant error classes, frequencies, package lists)
- KB patterns (existing knowledge)
- Prior cycle outcomes from strategy archive

**Output**:
- Research report (markdown) appended to knowledge base
- Key findings fed to Strategist as additional context

**Design**:
- System prompt includes: failure analysis summary, top error classes, package names, KB patterns
- Task: "Research solutions for [dominant_error_class] in Maven builds. Focus on: [specific error patterns]. Search for Maven docs, Stack Overflow solutions, similar project fixes."
- Agent uses WebSearch + WebFetch to find solutions
- Output written to `{cycle_dir}/research_report.md` and optionally appended to KB

**Integration in `run_intelligent_outer_loop()`**:
```python
# After step 2 (analyze_batch), before step 3 (propose_hypothesis):
research_report = _outer_researcher_research(analysis, kb_patterns)
# Feed research_report to strategist:
hypothesis = _outer_strategist_propose(analysis, archive, kb_patterns, research_report)
```

## 4. Risks and Potential Pitfalls

### 4.1 Subprocess Reliability
- **Risk**: Claude Code subprocess hangs or crashes, leaving the loop stuck.
- **Mitigation**: Set `timeout` on `subprocess.run()`. The inner loop Builder timeout should be ~120s (single Containerfile fix). The outer loop agents can be longer (~300s for Builder, ~180s for Strategist, ~300s for Researcher).
- **Risk**: Claude Code binary not available on the execution host (rh-h100-01).
- **Mitigation**: The inner loop currently runs podman builds via SSH on rh-h100-01, but the LLM call happens locally. With Claude Code subprocess, the LLM call still happens locally (where `claude` binary is installed). Verify `claude` is on PATH before entering the loop.

### 4.2 Output Parsing
- **Risk**: Claude Code agent output doesn't contain a valid Containerfile or JSON hypothesis.
- **Mitigation**: 
  - Inner Builder: Write Containerfile to temp file, have agent edit it in place, read it back. The file is always valid (it's an edited version of a previously valid file) or the agent's edit failed (revert to original).
  - Outer Strategist: Define a clear JSON schema in the system prompt, parse the output with fallback to the current hardcoded dict.
  - Post-process all Containerfile output through `sanitize_gha_expressions()`.

### 4.3 Test Breakage
- **Current test count**: 481 tests.
- **Tests that directly mock `AnthropicVertex`**: Tests in `test_outer_loop_v2.py` and `test_outer_strategist.py` mock the LLM calls. These will need to be updated to mock `subprocess.run` instead.
- **Tests that test data structures** (StrategyArchive, CodeChangeHypothesis, FailureAnalysis, etc.): These remain unchanged.
- **Risk**: The guard tests in `test_guards.py` test `check_surfaces()` with hardcoded MUTABLE_SURFACES. If new files are added (e.g., `outer_researcher.py`), MUTABLE_SURFACES needs updating — but this is a guard config change, not a test change.

### 4.4 Outer Builder Flow Change
- **Risk**: The current flow has `_outer_builder_implement()` return `{file_path: new_content}` which is applied atomically. If the Claude Code agent edits files directly, a crash mid-edit leaves partial changes on disk.
- **Mitigation**: 
  1. Save originals before launching the agent (current `_apply_changes` pattern)
  2. Or: have the agent work on a copy, then apply the changes atomically
  3. Or: use `git stash` to snapshot the working tree before the agent runs, revert via `git checkout -- .` if needed

### 4.5 Cost / Latency
- **Risk**: Claude Code subprocess is slower than a direct API call because it initializes a full agent runtime per invocation.
- **Impact**: Inner Builder is called once per iteration (up to 15 iterations per package). With 3 packages in a batch, that's up to 45 Claude Code subprocess spawns in a single outer loop batch run.
- **Mitigation**: The issue spec says "wall clock ~60 min is acceptable — correctness over speed." The additional overhead per subprocess spawn (~5-10s) adds at most ~7.5 min to a full batch, which is within budget.

### 4.6 Model Configuration
- **Risk**: The current code uses `AnthropicVertex(region="us-east5", project_id="itpc-gcp-ai-eng-claude")` for Vertex AI billing. Claude Code subprocess may not use Vertex AI by default.
- **Mitigation**: Configure Claude Code to use Vertex AI backend. The `claude` CLI supports `--model claude-opus-4-6` and can be configured for Vertex AI via environment variables or config file. Verify the billing configuration before E2E runs.

### 4.7 `--dangerously-skip-permissions`
- **Risk**: The Claude Code subprocess runs with `--dangerously-skip-permissions`, which means the agent can execute arbitrary commands without user confirmation.
- **Mitigation**: This is the factory pattern — the agents are designed to run autonomously. The guards (surface check, leakage scan, monotonic check, test gate) are the safety layer, not permission prompts. The system prompt constrains what the agent should do, but the guards verify what it actually did.
- **Note**: For the Inner Builder, the agent edits a temp Containerfile — it can't damage the source tree. For the Outer Builder, it edits source files — the guards + git revert provide safety.

### 4.8 Structured Output from Strategist
- **Risk**: The Claude Code Strategist agent needs to produce a valid `CodeChangeHypothesis` JSON. Free-form text output requires parsing.
- **Mitigation**: 
  - Use `--output-format json` and extract the `result` field
  - Include the exact JSON schema in the system prompt with explicit instructions
  - Wrap in a `try/except` with fallback to the current hardcoded dict approach
  - The `CodeChangeHypothesis` has only 5 fields — easy to validate

## 5. Test Strategy for Verifying Claude Code Agents

### 5.1 Unit Tests (mock subprocess)

For each migrated agent, mock `subprocess.run` and verify:

**Inner Builder tests**:
- `test_refine_spawns_claude_subprocess`: Verify the correct command is constructed (model, prompt file, task description)
- `test_refine_extracts_containerfile_from_output`: Mock subprocess output, verify Containerfile extraction
- `test_refine_applies_gha_sanitization`: Verify `sanitize_gha_expressions()` still runs on output
- `test_refine_handles_subprocess_timeout`: Verify graceful timeout handling
- `test_refine_handles_subprocess_error`: Verify error recovery (returns original Containerfile or raises)
- `test_meta_guidance_included_in_prompt`: Verify KB patterns flow into system prompt file
- `test_explore_uses_different_task`: Verify explore mode constructs a different task description
- `test_fresh_start_uses_different_task`: Verify fresh_start constructs metadata-only task

**Outer Builder tests**:
- `test_outer_builder_spawns_claude`: Verify subprocess command construction
- `test_outer_builder_no_200_line_cap`: Verify large files are not skipped
- `test_outer_builder_returns_changes`: Verify file changes are captured
- `test_outer_builder_handles_timeout`: Graceful timeout

**Outer Strategist tests**:
- `test_strategist_spawns_claude`: Verify subprocess command
- `test_strategist_parses_hypothesis_json`: Mock subprocess output with valid JSON, verify `CodeChangeHypothesis` creation
- `test_strategist_falls_back_on_invalid_json`: Verify fallback to hardcoded dict
- `test_strategist_includes_failure_analysis_in_prompt`: Verify context threading
- `test_strategist_includes_archive_in_prompt`: Verify strategy archive context

**Outer Researcher tests**:
- `test_researcher_spawns_claude`: Verify subprocess command
- `test_researcher_writes_report`: Verify output file creation
- `test_researcher_handles_timeout`: Graceful timeout
- `test_researcher_receives_failure_context`: Verify failure analysis flows into prompt

### 5.2 Integration Tests (real subprocess, mocked LLM)

These tests verify the full flow without actually calling Claude Code:
- `test_intelligent_outer_loop_cycle`: Full cycle with mocked subprocess returns
- `test_meta_guidance_flows_to_inner_builder`: Verify KB patterns reach the Builder's system prompt file

### 5.3 E2E Tests (real everything)

Per the issue spec, these are mandatory:
- **Inner loop E2E**: Run on 1 package (commons-lang3, known solvable) with real Claude Code Builder
  - Verify: Containerfile is valid, builds succeed, reward >= 0.98
- **Outer loop E2E**: Full cycle on 3+ packages
  - Verify: batch → analyze → research → strategize → implement → guard → re-batch → verdict
  - Each stage produces expected artifacts (failure_analysis.json, research_report.md, hypothesis.json)
  - Guard chain executes (surface check, leakage scan, monotonic check)

### 5.4 Regression Tests

- All 481 existing tests must pass
- `eval/score.py` must produce >= 0.55 composite score
- Smoke test: `python -m buildroot reconstruct org.apache.commons:commons-lang3:3.14.0` must still work

### 5.5 Files to Update for Tests

| Test File | Changes Needed |
|-----------|---------------|
| `tests/test_outer_loop_v2.py` | Update mocks from `AnthropicVertex` to `subprocess.run` |
| `tests/test_outer_strategist.py` | Update `propose_hypothesis` tests for Claude Code subprocess |
| `tests/test_guards.py` | Add `outer_researcher.py` to MUTABLE_SURFACES if needed |
| New: `tests/test_outer_researcher.py` | Full test suite for new Researcher agent |
| New: `tests/test_claude_subprocess.py` (optional) | Shared test utilities for subprocess mocking |

## 6. Implementation Order

Recommended phasing to minimize risk:

1. **Phase 1: Inner Builder** — highest impact, most isolated (only `builder.py` changes, `loop.py` interface unchanged)
2. **Phase 2: Outer Strategist** — replaces hardcoded dict, unlocks novel hypothesis generation
3. **Phase 3: Outer Researcher** — new module, no existing code to break
4. **Phase 4: Outer Builder** — most complex change (affects `outer_loop.py` flow), depends on Strategist producing real hypotheses
5. **Phase 5: E2E verification** — full loop validation

This order differs from the issue spec's ordering but minimizes integration risk: Inner Builder is self-contained, Strategist replaces a stub, Researcher is new code, and Outer Builder is the riskiest change that benefits from the other three being stable.

## 7. Key Helper: Subprocess Wrapper

All four agents will share the same Claude Code subprocess pattern. A small helper function avoids duplication:

```python
def run_claude_agent(
    system_prompt_path: str,
    task: str,
    model: str = "claude-opus-4-6",
    timeout: int = 300,
) -> str:
    """Spawn a Claude Code subprocess and return its text output."""
    result = subprocess.run(
        [
            "claude",
            "--append-system-prompt-file", system_prompt_path,
            "-p", task,
            "--output-format", "json",
            "--model", model,
            "--dangerously-skip-permissions",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    # Parse JSON output, extract result text
    output = json.loads(result.stdout)
    return output.get("result", "")
```

This should live in a shared utility (e.g., `src/buildroot/agent/claude_runner.py`) to avoid repeating the subprocess logic in each agent module.

## 8. MUTABLE_SURFACES Update

`guards.py:MUTABLE_SURFACES` will need to include new files:
- `src/buildroot/agent/outer_researcher.py` (new)
- `src/buildroot/agent/claude_runner.py` (new, if created)

And `factory.md` Mutable Surfaces section should be updated to match.
