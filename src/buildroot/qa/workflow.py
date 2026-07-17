"""QA workflow for buildroot — evaluation agent for L4 scoring.

Spawns the evaluation agent via spawn_claude_agent() to handle
JAR comparison + test recovery + scoring as a single independent session.
"""

import logging
from pathlib import Path
from buildroot.agent.claude_runner import spawn_claude_agent

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load an agent prompt from the prompts directory."""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text()


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
4. Save the report to {Path(containerfile_path).parent}/eval-agent-report.json
5. Return structured JSON with score, verdict, test results, and feedback"""

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

    prompt = _load_prompt("evaluation")

    result = spawn_claude_agent(
        task=task,
        system_prompt=prompt,
        json_schema=schema,
        max_turns=20,
        max_budget_usd=1.00,
        timeout=timeout,
        allowed_tools=["Bash", "Read"],
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
