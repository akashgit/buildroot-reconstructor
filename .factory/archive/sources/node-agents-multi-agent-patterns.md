---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-24
  - multi-agent
source: factory-archivist
date: 2026-06-15
research-type: external
---

# Multi-Agent Pipeline Architecture Patterns

## Finding

External research on multi-agent pipeline architectures yields several principles directly applicable to the node-scoped agent design.

## Key Principles

1. **Separate implement and review agents.** Collapsing these into one step caused immediate quality drops in production systems. The node agent approach inherently separates: deterministic step implements, Claude agent reviews.

2. **Strict scoping per agent.** Each agent needs: an objective, output format, tools/sources guidance, and clear task boundaries. Without this, agents duplicate work or leave gaps.

3. **Filesystem-based handoffs.** Agents write outputs to files and pass lightweight references, avoiding context overflow and information loss.

4. **3-7 agents per pipeline.** Beyond 7, coordination overhead outweighs benefits. For larger pipelines, use hierarchical structures. (Issue #24 specifies 13 agents — the external research recommends prioritizing the high-impact subset.)

5. **End-state evaluation over process checking.** Judge output correctness, not whether the agent followed prescribed steps.

## Model Selection for Node Agents

External research recommends Sonnet for reviewer agents (cheaper, fast enough for review tasks). Node agents are reviewers, not builders:
- Model: `claude-sonnet-4-6` (vs opus for builder agents)
- Budget: $0.25-0.50 per node (vs $5 for builders)
- Turns: 5-10 (vs 30)
- Timeout: 60-120s (vs 600s)

Estimated full benchmark cost: ~$1.24 at Sonnet pricing (31 packages × 4 priority agents × ~$0.01 each).

## Recommended Priority Ordering

| Priority | Agent | Rationale |
|----------|-------|-----------|
| High | POM Reviewer (steps 2-4) | Property inheritance, relocation, BOM edge cases |
| High | JDK Reviewer (step 8) | 12+ signal sources, tag verification needed |
| High | Image Reviewer (step 9) | Tag existence verification via Docker Hub API |
| High | Tag Reviewer (step 11) | Verify via `git ls-remote` |
| Medium | Build Cmd Reviewer (step 13b) | Plugin flag edge cases |

## Sources
- [Anthropic Multi-Agent Research System](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Multi-Agent Pipelines — Stephanie Jarmak](https://medium.com/@steph.jarmak)
- [How to Build Multi-Agent Systems: 2026 Guide — DEV Community](https://dev.to/eira-wexford/how-to-build-multi-agent-systems-complete-2026-guide-1io6)
- [Claude Code Sub-Agents — MindStudio](https://www.mindstudio.ai/blog/claude-code-sub-agents-explained)
