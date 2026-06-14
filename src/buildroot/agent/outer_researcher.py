"""Outer Researcher — Claude Code agent for web research on failure patterns."""

from __future__ import annotations

import logging
from pathlib import Path

from buildroot.agent.claude_runner import spawn_claude_agent
from buildroot.agent.failure_analyst import FailureAnalysis

logger = logging.getLogger(__name__)

RESEARCHER_MODEL = "claude-opus-4-6"

RESEARCHER_SYSTEM_PROMPT = """\
You are a research agent for a Maven build-environment reconstruction system.

Your job: given failure analysis from a batch of Maven package builds, research \
solutions for the dominant failure patterns using web search.

Focus on:
- Maven build error resolution techniques
- Containerfile / Dockerfile best practices for reproducible Java builds
- JDK version compatibility and selection strategies
- Maven plugin configuration and dependency resolution patterns

Output a concise research report in markdown with:
1. Summary of the dominant failure patterns
2. Relevant solutions found via web search
3. Actionable recommendations for the Strategist agent

Keep the report under 2000 words. Focus on actionable findings, not general advice.
"""


def research_failures(
    analysis: FailureAnalysis,
    kb_patterns: str = "",
    *,
    output_path: Path | None = None,
    model: str = RESEARCHER_MODEL,
    timeout: int = 600,
    max_budget_usd: float = 3.0,
) -> str:
    """Run the Outer Researcher agent to research failure patterns.

    Args:
        analysis: Failure analysis from the current batch.
        kb_patterns: Existing knowledge base patterns for context.
        output_path: Optional path to write the research report.
        model: Model identifier.
        timeout: Subprocess timeout in seconds.
        max_budget_usd: Dollar spend cap for the agent.

    Returns:
        Research report as markdown text, or empty string on failure.
    """
    error_summary = ""
    for ef in analysis.error_frequencies[:5]:
        error_summary += (
            f"- {ef.error_class}: {ef.count} packages "
            f"({', '.join(ef.packages[:3])})\n"
        )

    system_prompt = f"""\
{RESEARCHER_SYSTEM_PROMPT}

## Current Failure Analysis
Total packages: {analysis.total_packages}
Failed: {analysis.failed_packages}
Solved: {analysis.solved_packages}
Solve rate: {analysis.solve_rate:.4f}
Dominant error class: {analysis.dominant_error_class}

## Error Frequencies
{error_summary or "No errors recorded."}

## Existing Knowledge Base Patterns
{kb_patterns or "No prior patterns recorded."}
"""

    task = (
        f"Research solutions for Maven build failures, focusing on the dominant "
        f"error pattern: {analysis.dominant_error_class}. "
        f"Use web search to find relevant solutions, best practices, and "
        f"debugging techniques. Produce a concise research report."
    )

    agent_result = spawn_claude_agent(
        task=task,
        system_prompt=system_prompt,
        model=model,
        max_turns=20,
        max_budget_usd=max_budget_usd,
        timeout=timeout,
        allowed_tools=["Read", "WebSearch", "Bash"],
    )

    if agent_result.is_error:
        logger.error("Researcher agent failed: %s", agent_result.error_message)
        return ""

    report = agent_result.text.strip()

    if output_path and report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report + "\n")
        logger.info("Research report written to %s", output_path)

    logger.info(
        "Researcher produced %d-char report (cost=$%.2f)",
        len(report),
        agent_result.cost_usd,
    )
    return report
