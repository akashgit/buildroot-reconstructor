"""CLI command for the evaluation agent — spawns Claude to do L4 eval with test recovery."""

from __future__ import annotations

import json
import sys

import click


@click.command("eval-agent")
@click.argument("containerfile", type=click.Path(exists=True))
@click.argument("coordinate")
@click.option("--host", default=None, help="SSH host for remote builds")
@click.option("--timeout", default=900, type=int, help="Agent timeout in seconds")
@click.option("--pretty/--no-pretty", default=True, help="Pretty-print JSON output")
def eval_agent_cmd(containerfile, coordinate, host, timeout, pretty):
    """Spawn the evaluation agent for full L4 scoring with test recovery.

    This is the AUTHORITATIVE evaluator. It spawns an independent Claude
    session that runs JAR comparison (via buildroot eval), recovers and
    runs unit tests, computes the final score (70% JAR + 30% tests),
    and returns failure reasons with suggestions.

    The orchestrator should use this instead of buildroot eval directly.

    \b
    Examples:
        buildroot eval-agent Containerfile org.apache.commons:commons-lang3:3.14.0
        buildroot eval-agent my.Containerfile com.example:lib:1.0 --host myserver
    """
    from pathlib import Path
    from buildroot.agent.claude_runner import spawn_claude_agent

    cf_text = Path(containerfile).read_text()
    prompt_path = Path(__file__).parent.parent.parent / "qa" / "prompts" / "evaluation.md"
    prompt = prompt_path.read_text()

    host_info = f"SSH host: {host}" if host else "Local podman (no SSH)"

    task = f"""Evaluate the reconstructed artifact: {coordinate}

Containerfile path: {containerfile}

Containerfile:
```dockerfile
{cf_text}
```

Connection: {host_info}

Follow your evaluation pipeline:
1. Run `buildroot eval {containerfile} {coordinate}` to get JAR comparison
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

    click.echo("Spawning evaluation agent...", err=True)

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
        output = result.structured_output
    else:
        output = {
            "reward": 0.0,
            "l4_score": 0.0,
            "level_reached": 0,
            "comparison_verdict": "FAILED",
            "test_status": "error",
            "failure_reason": result.error_message or "Evaluation agent returned no structured output",
            "suggestion": "Check agent logs for details",
        }

    indent = 2 if pretty else None
    json.dump(output, sys.stdout, indent=indent)
    print()

    reward = output.get("reward", 0)
    test_status = output.get("test_status", "unknown")
    tests_run = output.get("tests_run", 0)

    if reward >= 0.98:
        click.echo(f"EVAL PASSED: reward={reward}, tests={tests_run} ({test_status})", err=True)
    else:
        reason = output.get("failure_reason", "unknown")
        click.echo(f"EVAL: reward={reward}, tests={tests_run} ({test_status})", err=True)
        click.echo(f"  Reason: {reason}", err=True)
        suggestion = output.get("suggestion", "")
        if suggestion:
            click.echo(f"  Suggestion: {suggestion}", err=True)
        sys.exit(1)
