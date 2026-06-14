# External Research: Claude Code Subprocess Spawning Patterns

## Context

Issue #19 requires replacing raw `AnthropicVertex` API calls in 4 agents (Inner Builder, Outer Builder, Outer Strategist, and new Outer Researcher) with Claude Code subprocess spawning (`claude -p` pattern). This research covers the exact CLI flags, Python subprocess patterns, structured output, error handling, and system prompt customization needed for the implementation.

---

## 1. Core CLI Pattern: `claude -p`

The `claude -p` (or `--print`) flag runs Claude Code in non-interactive/headless mode. This is the foundation for all agent subprocess spawning.

**Canonical invocation:**
```bash
claude -p "task description" \
  --append-system-prompt-file ./prompt.txt \
  --output-format json \
  --allowedTools "Read,Edit,Bash" \
  --model claude-opus-4-6 \
  --max-turns 30 \
  --max-budget-usd 5.00 \
  --dangerously-skip-permissions
```

**Key behaviors:**
- Reads stdin (can pipe data in)
- Piped stdin capped at 10MB — for larger inputs, write to a file and reference in the prompt
- Exits with code 0 on success, 1 on error
- 3–5 second startup overhead per subprocess (Node.js startup, CLI init, auth handshake)
- Background Bash tasks are terminated ~5 seconds after the main result returns

**Source:** [Run Claude Code programmatically](https://code.claude.com/docs/en/headless)

---

## 2. System Prompt Customization

Four flags control the system prompt, all work in both interactive and non-interactive modes:

| Flag | Behavior |
|---|---|
| `--system-prompt "text"` | Replaces the entire default prompt |
| `--system-prompt-file ./file.txt` | Replaces with file contents |
| `--append-system-prompt "text"` | Appends to the default prompt |
| `--append-system-prompt-file ./file.txt` | Appends file contents to the default prompt |

**Decision guidance:**
- **Use `--append-system-prompt-file`** for our agents — they should remain coding assistants (Read/Edit/Bash/WebSearch) with additional domain-specific rules. This preserves the default tool guidance, safety instructions, and coding conventions.
- `--system-prompt` and `--system-prompt-file` are mutually exclusive. The append flags can be combined with either replacement flag.
- These flags apply only to the current invocation. For persistent personas, use output styles or CLAUDE.md.

**For our implementation:** Each agent (Inner Builder, Outer Builder, Outer Strategist, Outer Researcher) should use `--append-system-prompt-file` with a per-agent prompt file written to a temp directory before spawning. The prompt file includes the agent role, constraints, current context (error analysis, dead-end registry, spec metadata), and expected output format.

**Source:** [CLI reference — System prompt flags](https://code.claude.com/docs/en/cli-reference), [Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts)

---

## 3. Structured Output with `--json-schema`

For agents that need to return structured data (e.g., Outer Strategist returning `CodeChangeHypothesis`):

```bash
claude -p "Generate a hypothesis" \
  --output-format json \
  --json-schema '{"type":"object","properties":{"target_error_class":{"type":"string"},...},"required":[...]}'
```

**Key details:**
- `--output-format json` is REQUIRED — text mode doesn't include `structured_output`
- The response JSON includes metadata (session ID, usage, cost) plus:
  - `result` — the agent's text response
  - `structured_output` — validated object matching the schema (when `--json-schema` is used)
  - `is_error` — boolean indicating failure
  - `total_cost_usd` — cost tracking
- Parse with `jq -r '.structured_output'` or Python's `json.loads(stdout)["structured_output"]`
- Not constrained generation — the model produces the JSON and it's validated post-hoc

**For our implementation:**
- **Outer Strategist**: Use `--json-schema` with `CodeChangeHypothesis` schema to get structured hypothesis output
- **Inner Builder**: Use plain `--output-format json` and extract `result` (the Containerfile text)
- **Outer Researcher**: Use plain `--output-format json` and extract `result` (research report markdown)

**Source:** [Run Claude Code programmatically — Get structured output](https://code.claude.com/docs/en/headless)

---

## 4. Bare Mode for Faster Startup

```bash
claude --bare -p "task" --append-system-prompt-file ./prompt.txt --allowedTools "Read,Edit,Bash"
```

**What `--bare` skips:** hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md auto-discovery. Claude retains access to Bash, file read, and file edit tools.

**Why it matters for us:**
- Reduces startup overhead (no CLAUDE.md discovery, no MCP server init)
- Makes invocations deterministic — no ambient state from the environment
- Recommended mode for scripted/SDK calls; will become the default for `-p` in a future release
- Pass context explicitly via flags rather than relying on auto-discovery

**Caveat:** `--bare` skips OAuth and keychain reads. Authentication must come from `ANTHROPIC_API_KEY` or `apiKeyHelper` in `--settings`. For Vertex AI, provider credentials are used directly (which is what we need — AnthropicVertex region=us-east5).

**Source:** [Bare mode documentation](https://code.claude.com/docs/en/headless#start-faster-with-bare-mode)

---

## 5. Python Subprocess Pattern

### Recommended implementation pattern:

```python
import json
import subprocess
import tempfile
from pathlib import Path

def spawn_claude_agent(
    task: str,
    system_prompt: str,
    *,
    model: str = "claude-opus-4-6",
    json_schema: dict | None = None,
    max_turns: int = 30,
    max_budget_usd: float = 5.0,
    timeout: int = 600,
    cwd: str | None = None,
) -> dict:
    """Spawn a Claude Code agent as subprocess and return parsed result."""
    
    # Write system prompt to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as f:
        f.write(system_prompt)
        prompt_file = f.name
    
    try:
        cmd = [
            "claude",
            "--bare",
            "-p", task,
            "--append-system-prompt-file", prompt_file,
            "--output-format", "json",
            "--model", model,
            "--max-turns", str(max_turns),
            "--max-budget-usd", str(max_budget_usd),
            "--dangerously-skip-permissions",
        ]
        
        if json_schema:
            cmd.extend(["--json-schema", json.dumps(json_schema)])
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        
        if result.returncode != 0:
            return {
                "is_error": True,
                "error": result.stderr or "Non-zero exit code",
                "result": result.stdout,
            }
        
        return json.loads(result.stdout)
    
    except subprocess.TimeoutExpired:
        return {
            "is_error": True,
            "error": f"Agent timed out after {timeout}s",
            "result": "",
        }
    except json.JSONDecodeError as e:
        return {
            "is_error": True,
            "error": f"Failed to parse JSON output: {e}",
            "result": result.stdout if 'result' in dir() else "",
        }
    finally:
        Path(prompt_file).unlink(missing_ok=True)
```

### Key considerations:
1. **Timeout**: Use `subprocess.run(timeout=...)` — catch `subprocess.TimeoutExpired`
2. **Exit codes**: 0 = success, 1 = error. Also check `is_error` in JSON output
3. **Large inputs**: Write to temp files and reference paths in the prompt, don't pipe >10MB
4. **Working directory**: Use `cwd=` parameter to set the agent's working directory (important for file edits)
5. **Error handling**: Catch `FileNotFoundError` (claude not installed), `subprocess.TimeoutExpired`, `json.JSONDecodeError`

---

## 6. Permission Modes and Tool Access

### For our agents:

```bash
# Option 1: Bypass all permissions (recommended for automated pipelines)
--dangerously-skip-permissions

# Option 2: Auto mode (classifier checks each action, safer)
--permission-mode auto

# Option 3: Explicit tool allowlisting
--allowedTools "Read,Edit,Bash(git *),Bash(mvn *),WebSearch"
```

**`--dangerously-skip-permissions` details:**
- Skips ALL permission prompts — every action executes immediately
- Designed for headless/CI environments where no human is at the keyboard
- **All subagents inherit bypass mode** — no secondary checks
- Deny rules (`--disallowedTools`) STILL apply even in bypass mode
- **Safety mitigation**: Run in a container or isolated worktree, not bare metal

**For our implementation:**
- Use `--dangerously-skip-permissions` since agents run in controlled pipeline
- Add `--disallowedTools` deny rules to prevent dangerous operations:
  ```
  --disallowedTools "Bash(rm -rf *)" "Bash(git push *)" "Bash(git reset *)"
  ```
- The Inner Builder should work in a temp directory, not the main repo
- The Outer Builder should work in a git worktree for isolation

**Source:** [Claude Code --dangerously-skip-permissions guide](https://www.truefoundry.com/blog/claude-code-dangerously-skip-permissions), [Permission modes](https://code.claude.com/docs/en/permission-modes)

---

## 7. Cost Control and Turn Limits

| Flag | Purpose | Behavior |
|---|---|---|
| `--max-turns N` | Limit agentic turns | Exits with error when reached; `subtype == "success"` (no distinct error subtype) |
| `--max-budget-usd N` | Limit dollar spend | Exits with `subtype == "error_max_budget_usd"` when exceeded |

**Recommended settings per agent:**

| Agent | max-turns | max-budget-usd | timeout (seconds) |
|---|---|---|---|
| Inner Builder | 30 | 5.00 | 600 (10 min) |
| Outer Builder | 30 | 5.00 | 600 (10 min) |
| Outer Strategist | 10 | 2.00 | 300 (5 min) |
| Outer Researcher | 20 | 3.00 | 600 (10 min) |

**Source:** [Resource Limits and Cost Control](https://deepwiki.com/anthropics/claude-agent-sdk-python/6.3-security-and-sandbox-settings)

---

## 8. Streaming vs Batch Output

For our pipeline, **batch output (`--output-format json`)** is the right choice:
- We need the complete result before proceeding
- Structured output only works with batch JSON
- No need for real-time token streaming in automated pipeline

For debugging/monitoring, `--output-format stream-json --verbose` can be used to watch agent progress in real-time. Each line is a JSON event. Useful for development but not for production pipeline.

---

## 9. Token Cost Awareness

Each `claude -p` subprocess starts fresh with the full system prompt. Without `--bare`, the system loads global config, CLAUDE.md, hooks, etc. — this can be **~50K tokens of overhead per invocation** before any actual work.

**Mitigations:**
1. Use `--bare` to eliminate ambient config loading
2. Use `--append-system-prompt-file` (not full system prompt replacement) to leverage prompt caching
3. Use `--exclude-dynamic-system-prompt-sections` for cross-invocation cache reuse
4. Keep system prompts concise — only include what the agent needs for its specific task

**For our agents:** With `--bare` + `--append-system-prompt-file`, we should see ~10-15K tokens for system setup per invocation, not 50K.

**Source:** [Building a 24/7 Claude Code Wrapper](https://dev.to/jungjaehoon/why-claude-code-subagents-waste-50k-tokens-per-turn-and-how-to-fix-it-41ma)

---

## 10. Vertex AI Integration

Since we're using `AnthropicVertex(region='us-east5', project_id='itpc-gcp-ai-eng-claude')`, the Claude Code subprocess needs Vertex AI credentials:

**Required environment variables:**
```bash
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_REGION=us-east5
export ANTHROPIC_VERTEX_PROJECT_ID=itpc-gcp-ai-eng-claude
```

Or pass via `--settings`:
```bash
claude --settings '{"apiProvider":"vertex","vertexRegion":"us-east5","vertexProjectId":"itpc-gcp-ai-eng-claude"}' ...
```

The `--model` flag works with Vertex — pass `claude-opus-4-6` as the model name.

---

## 11. Agent SDK Alternative (Python Package)

The `claude-agent-sdk` Python package (`pip install claude-agent-sdk`) provides a native async API:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Fix this Containerfile",
    options=ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": "You are a Containerfile expert...",
        },
        max_turns=30,
        max_budget_usd=5.0,
    ),
):
    ...
```

**Tradeoffs vs subprocess:**
| Feature | `subprocess.run` + `claude -p` | Agent SDK |
|---|---|---|
| Structured JSON output | `--output-format json --json-schema` | Open issue (#180) |
| Debugging | Run exact same command manually | Harder to reproduce |
| Overhead | 3-5s startup per call | Same (spawns CLI internally) |
| Session management | `--continue` / `--resume` | `ClaudeSDKClient` |
| CI/CD compatibility | Excellent | OAuth complications |
| Vertex AI auth | Env vars | Env vars |

**Recommendation:** Use `subprocess.run` + `claude -p` for this implementation. It's simpler, more debuggable, supports structured output via `--json-schema`, and avoids the async complexity of the SDK. The SDK's main advantage (bidirectional streaming) isn't needed for our batch pipeline.

**Source:** [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python)

---

## 12. Error Handling Patterns

### Exit code handling:
```python
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
if result.returncode != 0:
    # Agent failed — check stderr for details
    logger.error("Agent failed: %s", result.stderr)
```

### JSON-level error detection:
```python
output = json.loads(result.stdout)
if output.get("is_error"):
    # Agent reported an error
    error_subtype = output.get("subtype", "unknown")
    # Possible subtypes: "error_max_budget_usd", "success" (for max-turns), etc.
```

### API retry events (stream-json mode):
When an API request fails with a retryable error, Claude Code emits a `system/api_retry` event with:
- `attempt` — current attempt number
- `max_retries` — total retries permitted
- `retry_delay_ms` — milliseconds until next attempt
- `error` — error category: `rate_limit`, `overloaded`, `server_error`, etc.

### Common failure modes and mitigations:
| Failure | Detection | Mitigation |
|---|---|---|
| Timeout | `subprocess.TimeoutExpired` | Increase timeout, reduce max-turns |
| Budget exceeded | `subtype == "error_max_budget_usd"` | Increase budget or reduce scope |
| Rate limit | API retry events (auto-handled) | Claude Code retries automatically |
| Parse error | `json.JSONDecodeError` | Check stdout for partial output |
| Claude not found | `FileNotFoundError` | Check PATH, install claude |
| Vertex auth failure | Non-zero exit, auth error in stderr | Check env vars |

---

## 13. Working Directory and File Access

Agents operate relative to their working directory:
- Use `subprocess.run(..., cwd="/path/to/project")` to set it
- `--add-dir` grants access to additional directories
- With `--bare`, only explicitly passed context is available

**For our agents:**
- **Inner Builder**: `cwd` = project root, so it can read spec files and write Containerfiles
- **Outer Builder**: `cwd` = project root, so it can edit source files under `src/`
- **Outer Strategist**: `cwd` = project root, for reading failure analysis and KB
- **Outer Researcher**: `cwd` = project root, for reading failure analysis and writing reports

---

## 14. Prior Knowledge from Archive

### Relevant archive sources:

1. **codex-iterative-repair.md**: Validates our Analyzer→Builder→Evaluator separation pattern. "Separates judgment from proof: Review→Repair→Validation as distinct phases with structured outputs."

2. **sgagent-multi-agent-repair.md**: Multi-agent repair with escalation thresholds (3x/2x). Maps to our G_t mode switching (exploit→explore→meta-shift).

3. **mini-swe-agent-lightweight-repair.md**: Context management is critical — use "memory pointer" pattern (store full log externally, pass key lines to LLM). Our `build_log_summary` field (<=500 chars) follows this.

4. **llmloop-iterative-feedback.md**: Per-error-class prompt templates. Different failure modes benefit from different prompts. Informs how KB entries should structure error-class-specific Builder instructions.

5. **repairagent-icse2025.md**: Agent-driven tool selection outperforms fixed pipelines. Validates giving Claude Code agents autonomy to choose their approach rather than following predetermined fix sequences.

6. **meta-harness-optimization.md**: "Full history exposure via filesystem is superior to compressed summaries." Validates keeping strategy archive records accessible as files.

---

## 15. Implementation Recommendations

### Architecture:

```
spawn_claude_agent(task, system_prompt, ...)
├── Write system prompt to temp file
├── Build command: claude --bare -p ... --append-system-prompt-file ...
├── subprocess.run(cmd, timeout=T, cwd=project_root)
├── Parse JSON output
├── Extract result/structured_output
└── Clean up temp files
```

### Per-agent configurations:

**Inner Builder:**
- System prompt: agent role + current Containerfile + error analysis + dead-ends + spec + meta_guidance
- Task prompt: "Fix this Containerfile" (refine) / "Try a different approach" (explore) / "Generate from scratch" (fresh_start)
- Output: plain text Containerfile in `result` field
- Tools needed: Read, Edit, Bash, WebSearch
- Post-processing: `sanitize_gha_expressions()` on output

**Outer Builder:**
- System prompt: hypothesis + target files list + constraints + style guide
- Task prompt: "Implement this hypothesis by editing the target files"
- Output: plain text summary of changes in `result` field (actual changes made via Edit tool)
- Tools needed: Read, Edit, Bash (for running tests)
- No file size cap — Edit tool handles any size

**Outer Strategist:**
- System prompt: failure analysis + KB patterns + archive (recent J scores + verdicts) + mutable surfaces
- Task prompt: "Analyze failure patterns and generate a code change hypothesis"
- Output: `CodeChangeHypothesis` JSON via `--json-schema`
- Tools needed: Read, WebSearch (optional)
- Lower max-turns (10) — strategy generation shouldn't need many iterations

**Outer Researcher (NEW):**
- System prompt: failure analysis + KB + prior cycle outcomes
- Task prompt: "Research solutions for these failure patterns: [dominant errors]"
- Output: markdown research report in `result` field
- Tools needed: Read, WebSearch, Bash (for searching codebase)
- Runs between Failure Analyst and Strategist

### Shared utility function:

All 4 agents should share a common `spawn_claude_agent()` function in a new `src/buildroot/agent/claude_runner.py` module. This function handles:
- Temp file management for system prompts
- Subprocess invocation with timeout
- JSON parsing and error handling
- Cost tracking and logging
- Vertex AI credential setup

---

## References

- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless)
- [CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts)
- [Permission modes](https://code.claude.com/docs/en/permission-modes)
- [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python)
- [Wrapping Claude CLI for Agentic Applications](https://avasdream.com/blog/claude-cli-agentic-wrapper)
- [Building a 24/7 Claude Code Wrapper — Token Cost Analysis](https://dev.to/jungjaehoon/why-claude-code-subagents-waste-50k-tokens-per-turn-and-how-to-fix-it-41ma)
- [Claude Code --dangerously-skip-permissions Safety Guide](https://www.truefoundry.com/blog/claude-code-dangerously-skip-permissions)
- [Structured CLI Output as Pipeline Glue](https://stevekinney.com/courses/self-testing-ai-agents/structured-cli-output-as-pipeline-glue)
- [Resource Limits and Cost Control](https://deepwiki.com/anthropics/claude-agent-sdk-python/6.3-security-and-sandbox-settings)
- [How Claude Code Builds a System Prompt](https://www.dbreunig.com/2026/04/04/how-claude-code-builds-a-system-prompt.html)
