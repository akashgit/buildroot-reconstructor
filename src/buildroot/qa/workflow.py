"""QA workflow for buildroot — test recovery + verification pipeline.

Adapted from refactory-midstream's deep-QA pattern (PR #264, #266).
Uses spawn_claude_agent() to run specialist agents in sequence:

    test_recovery_agent → verification_agent → combine results
"""

import json
import logging
from pathlib import Path
from buildroot.agent.claude_runner import spawn_claude_agent
from buildroot.agent.models import TestResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

def _load_prompt(name: str) -> str:
    """Load an agent prompt from the prompts directory."""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text()

def run_test_recovery(
    tag: str,
    containerfile: str,
    coordinate: str,
    *,
    host: str | None = None,
    timeout: int = 600,
    podman_root: str | None = None,
    podman_runroot: str | None = None,
    podman_tmpdir: str | None = None,
) -> TestResult:
    """Run the test recovery agent to find and execute unit tests.

    Returns a TestResult with four-way status classification.
    """
    # Build the task description with all context
    podman_info = []
    if host:
        podman_info.append(f"SSH host: {host}")
    if podman_root:
        podman_info.append(f"podman --root {podman_root}")
    if podman_runroot:
        podman_info.append(f"podman --runroot {podman_runroot}")
    if podman_tmpdir:
        podman_info.append(f"podman --tmpdir {podman_tmpdir}")
    podman_str = "\n".join(podman_info) if podman_info else "Local podman (no SSH)"

    task = f"""Recover and run unit tests for: {coordinate}

Container image tag: {tag}

Containerfile:
```dockerfile
{containerfile}
```

Podman connection:
{podman_str}

Analyze the Containerfile, probe for test sources, and attempt to run tests.
Return your findings as structured JSON."""

    schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["passed", "failed", "no_tests", "not_reached", "timeout", "error"],
            },
            "tests_run": {"type": "integer"},
            "tests_passed": {"type": "integer"},
            "tests_failed": {"type": "integer"},
            "tests_skipped": {"type": "integer"},
            "framework": {"type": "string"},
            "command_used": {"type": "string"},
            "duration_seconds": {"type": "number"},
            "failures": {"type": "array", "items": {"type": "string"}},
            "recovery_attempted": {"type": "boolean"},
            "recovery_details": {"type": "string"},
        },
        "required": ["status", "tests_run", "tests_passed", "tests_failed", "framework"],
    }

    prompt = _load_prompt("test_recovery_agent")

    result = spawn_claude_agent(
        task=task,
        system_prompt=prompt,
        json_schema=schema,
        max_turns=15,
        max_budget_usd=0.50,
        timeout=timeout,
    )

    if result.structured_output:
        data = result.structured_output
        return TestResult(
            available=True,
            framework=data.get("framework", ""),
            command=data.get("command_used", ""),
            passed=data.get("status") == "passed",
            run=data.get("tests_run", 0),
            tests_passed=data.get("tests_passed", 0),
            failed=data.get("tests_failed", 0),
            skipped=data.get("tests_skipped", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            failures=data.get("failures", []),
            status=data.get("status", "error"),
        )

    # Agent failed — fall back to error status
    logger.warning("Test recovery agent failed: %s", result.error_message or "no structured output")
    return TestResult(
        available=True,
        framework="",
        command="",
        passed=False,
        status="error",
    )
