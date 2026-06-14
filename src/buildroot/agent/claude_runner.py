"""Shared Claude Code subprocess runner for all agent invocations."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-6"


@dataclass
class AgentResult:
    """Result from a Claude Code subprocess invocation."""

    text: str
    structured_output: dict | None = None
    is_error: bool = False
    error_message: str = ""
    cost_usd: float = 0.0
    num_turns: int = 0

    @property
    def ok(self) -> bool:
        return not self.is_error


def spawn_claude_agent(
    task: str,
    system_prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    json_schema: dict | None = None,
    max_turns: int = 30,
    max_budget_usd: float = 5.0,
    timeout: int = 600,
    cwd: str | None = None,
    allowed_tools: list[str] | None = None,
) -> AgentResult:
    """Spawn a Claude Code agent as a subprocess and return the parsed result.

    Args:
        task: The task description passed via ``-p``.
        system_prompt: Content written to a temp file and passed via
            ``--append-system-prompt-file``.
        model: Model identifier (default ``claude-opus-4-6``).
        json_schema: If provided, passed via ``--json-schema`` for structured output.
        max_turns: Maximum agentic turns.
        max_budget_usd: Dollar spend cap.
        timeout: Subprocess timeout in seconds.
        cwd: Working directory for the agent process.
        allowed_tools: Optional list of allowed tools (e.g. ``["Read", "Edit", "Bash"]``).
    """
    prompt_file: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="claude_prompt_"
        ) as f:
            f.write(system_prompt)
            prompt_file = f.name

        cmd = [
            "claude",
            "--bare",
            "-p", task,
            "--append-system-prompt-file", prompt_file,
            "--output-format", "json",
            "--model", model,
            "--max-turns", str(max_turns),
            "--dangerously-skip-permissions",
        ]

        if max_budget_usd > 0:
            cmd.extend(["--max-budget-usd", str(max_budget_usd)])

        if json_schema:
            cmd.extend(["--json-schema", json.dumps(json_schema)])

        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])

        logger.info("Spawning Claude agent: model=%s, max_turns=%d, timeout=%ds", model, max_turns, timeout)
        logger.debug("Agent task: %s", task[:200])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )

        if result.returncode != 0:
            error_detail = result.stderr.strip() or f"Exit code {result.returncode}"
            logger.error("Claude agent failed: %s", error_detail[:500])
            return AgentResult(
                text=result.stdout,
                is_error=True,
                error_message=error_detail,
            )

        output = json.loads(result.stdout)

        return AgentResult(
            text=output.get("result", ""),
            structured_output=output.get("structured_output"),
            is_error=output.get("is_error", False),
            error_message=output.get("error", ""),
            cost_usd=output.get("total_cost_usd", 0.0),
            num_turns=output.get("num_turns", 0),
        )

    except FileNotFoundError:
        msg = "Claude Code CLI not found — ensure 'claude' is on PATH"
        logger.error(msg)
        return AgentResult(text="", is_error=True, error_message=msg)

    except subprocess.TimeoutExpired:
        msg = f"Claude agent timed out after {timeout}s"
        logger.error(msg)
        return AgentResult(text="", is_error=True, error_message=msg)

    except json.JSONDecodeError as e:
        msg = f"Failed to parse Claude agent JSON output: {e}"
        logger.error(msg)
        return AgentResult(text="", is_error=True, error_message=msg)

    finally:
        if prompt_file:
            Path(prompt_file).unlink(missing_ok=True)
