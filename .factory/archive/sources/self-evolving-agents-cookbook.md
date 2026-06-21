---
tags:
  - factory
  - source
  - agent-architecture
source: factory-archivist
date: 2026-06-16
---

# Self-Evolving Agents — OpenAI Cookbook

**Source**: [Self-Evolving Agents Cookbook (OpenAI)](https://developers.openai.com/cookbook/examples/partners/self_evolving_agents/autonomous_agent_retraining)

## Architecture

Four-step Generate→Evaluate→Optimize→Accept loop with versioned prompts:

- `collect_grader_feedback()` translates failures into structured reasoning that feeds the optimizer
- `VersionedPrompt` class tracks full history with scores per version

## Relevance

Maps to AnalyzeAgent translating build logs into playbook entries. The `collect_grader_feedback()` function is analogous to AnalyzeAgent's failure-to-playbook-entry translation.

For buildroot playbooks, the equivalent of `VersionedPrompt` scoring is the `helpful`/`harmful` counters — they track whether a rule is working over time without storing full version history. This is simpler and sufficient for our use case where individual rules are atomic and independently verifiable.
