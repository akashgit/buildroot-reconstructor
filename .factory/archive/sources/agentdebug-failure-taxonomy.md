---
tags:
  - factory
  - source
  - agent-architecture
source: factory-archivist
date: 2026-06-16
---

# AgentDebug — Root-Cause Isolation via Failure Taxonomy

**Paper**: [AgentDebug: Learning from Agent Failures (Sep 2025)](https://arxiv.org/abs/2509.25370)

## Key Contribution

Provides a modular failure taxonomy (memory, reflection, planning, action, system-level) and a debugging framework that "isolates root-cause failures and provides corrective feedback, enabling agents to recover with up to 26% relative improvement."

## Relevance to AnalyzeAgent

Validates the AnalyzeAgent's core function: connecting build failures to the responsible node agent (root cause isolation) and writing targeted feedback. The taxonomy maps to buildroot's failure modes:

- **Action failures** → wrong build command, wrong image tag
- **Planning failures** → wrong build tool selection (lz4-java Maven vs Gradle)
- **Memory failures** → fixes not persisting across iterations (Gap 3)
- **System failures** → SSH key issues, Podman short-name resolution

The 26% improvement from targeted corrective feedback supports the expected impact of per-agent playbook entries.

## Implementation Guidance

Root cause → responsible agent mapping should be structured, not free-text. The AnalyzeAgent should output which specific node agent's decision caused the failure, enabling targeted playbook updates rather than generic advice.
