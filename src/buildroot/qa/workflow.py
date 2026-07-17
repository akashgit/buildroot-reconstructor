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


def run_verification(
    tag: str,
    containerfile: str,
    coordinate: str,
    *,
    host: str | None = None,
    timeout: int = 300,
    podman_root: str | None = None,
    podman_runroot: str | None = None,
    podman_tmpdir: str | None = None,
) -> dict:
    """Run the verification agent for programmatic JAR checks.

    Returns a dict with structural, bytecode, metadata match results.
    """
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

    task = f"""Verify the reconstructed build for: {coordinate}

Container image tag: {tag}

Containerfile:
```dockerfile
{containerfile}
```

Podman connection:
{podman_str}

Run `buildroot eval` against this Containerfile and coordinate, then report the
L1-L4 results. Check structural match, bytecode version, metadata, and manifest.
Return your findings as structured JSON."""

    schema = {
        "type": "object",
        "properties": {
            "l1_parse": {"type": "boolean"},
            "l2_build": {"type": "boolean"},
            "l3_command": {"type": "boolean"},
            "l4_score": {"type": "number"},
            "l4_match": {"type": "boolean"},
            "comparison_verdict": {"type": "string"},
            "reward": {"type": "number"},
            "structural_match": {"type": "boolean"},
            "bytecode_match": {"type": "boolean"},
            "metadata_match": {"type": "boolean"},
        },
        "required": ["l1_parse", "l2_build", "l3_command", "reward"],
    }

    prompt = _load_prompt("verification_agent")

    result = spawn_claude_agent(
        task=task,
        system_prompt=prompt,
        json_schema=schema,
        max_turns=10,
        max_budget_usd=0.30,
        timeout=timeout,
    )

    if result.structured_output:
        return result.structured_output

    logger.warning("Verification agent failed: %s", result.error_message or "no structured output")
    return {"error": result.error_message or "no structured output"}


def run_l4_eval(
    containerfile_path: str,
    containerfile_text: str,
    coordinate: str,
    *,
    host: str | None = None,
    timeout: int = 900,
) -> dict:
    """Run the L4-eval agent — complete evaluation with test recovery.

    Spawns a single Claude agent that handles JAR comparison + test recovery
    + scoring + feedback. Returns the full evaluation result as a dict.
    """
    host_info = f"SSH host: {host}" if host else "Local podman (no SSH)"

    task = f"""Evaluate the reconstructed artifact: {coordinate}

Containerfile path: {containerfile_path}

Containerfile:
```dockerfile
{containerfile_text}
```

Connection: {host_info}

Follow your evaluation pipeline:
1. Run `buildroot eval {containerfile_path} {coordinate}` to get JAR comparison
2. Probe the container for test sources and run them
3. Compute the final score (70% JAR + 30% tests)
4. Return structured JSON with score, verdict, test results, and feedback"""

    schema = {
        "type": "object",
        "properties": {
            "reward": {"type": "number"},
            "l4_score": {"type": "number"},
            "jar_score": {"type": "number"},
            "level_reached": {"type": "integer"},
            "comparison_verdict": {"type": "string"},
            "test_status": {
                "type": "string",
                "enum": ["passed", "failed", "no_tests", "not_reached", "timeout", "error"],
            },
            "tests_run": {"type": "integer"},
            "tests_passed": {"type": "integer"},
            "tests_failed": {"type": "integer"},
            "tests_skipped": {"type": "integer"},
            "test_framework": {"type": "string"},
            "test_command": {"type": "string"},
            "test_failures": {"type": "array", "items": {"type": "string"}},
            "failure_reason": {"type": "string"},
            "suggestion": {"type": "string"},
        },
        "required": ["reward", "l4_score", "level_reached", "comparison_verdict", "test_status"],
    }

    prompt = _load_prompt("l4_eval_agent")

    result = spawn_claude_agent(
        task=task,
        system_prompt=prompt,
        json_schema=schema,
        max_turns=20,
        max_budget_usd=1.00,
        timeout=timeout,
        allowed_tools=["Bash", "Read", "Write", "Edit"],
    )

    if result.structured_output:
        return result.structured_output

    logger.warning("L4-eval agent failed: %s", result.error_message or "no structured output")
    return {
        "reward": 0.0,
        "l4_score": 0.0,
        "level_reached": 0,
        "comparison_verdict": "FAILED",
        "test_status": "error",
        "failure_reason": result.error_message or "L4-eval agent returned no structured output",
        "suggestion": "Check agent logs for details",
    }
