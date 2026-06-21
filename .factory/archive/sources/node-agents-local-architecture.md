---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-24
source: factory-archivist
date: 2026-06-15
research-type: local
---

# Node-Scoped Agents — Local Architecture Analysis

## Finding

The 13-step deterministic pipeline in `BuildrootOrchestrator.reconstruct()` (orchestrator.py:78-229) maps directly to 10 node agents + 3 post-build failure agents. Each pipeline step has a clear insertion point where a scoped Claude Code agent can review and improve the step's output.

## Pipeline Step → Agent Mapping

| Step | Code | Node Agent |
|------|------|------------|
| 1-2 | `fetch_pom()` + `PomParser.parse()` | Node 1: POM Agent |
| 3-4 | `resolve_parent_chain()` + `merge_poms()` | Node 2: Parent Chain Agent |
| 5 | `PropertyResolver.resolve()` | Node 3: Property Agent |
| 6 | `discover_repo_from_pom()` | Node 4: Repo Agent |
| 7 | `CIParser.discover_ci_type()` + parse | Node 5: CI Agent |
| 8 | `JdkResolver.resolve()` | Node 6: JDK Agent |
| 9 | `ContainerImageResolver.resolve()` | Node 7: Image Agent |
| 11 | `discover_git_tag()` | Node 8: Tag Agent |
| 12 | `_detect_maven_wrapper_version()` + `_enrich_build_commands()` | Node 9: Build Cmd Agent |
| 13 | `GapDetector.analyze()` + `ContainerfileGenerator.generate()` | Node 10: Template Agent |

## Integration Architecture: AgentAugmentedObserver

Recommended approach (Option C from issue analysis):
1. Run full deterministic pipeline → draft `BuildrootSpec`
2. Run `GapDetector.analyze(spec)` → gap report with per-field source classifications
3. Fire node agents per gap classification (DEFAULTED=always, INFERRED=standard, OBSERVED=validate-only)
4. Each node agent updates the spec → re-render Containerfile

This avoids refactoring `orchestrator.py` — the deterministic pipeline stays clean.

## Infrastructure Readiness

- `spawn_claude_agent()` in `claude_runner.py` is proven (used by 4 agents already)
- Supports structured output via `--json-schema`, tool scoping via `--allowedTools`
- `GapDetector` already classifies 6 dimensions as OBSERVED/INFERRED/DEFAULTED
- `ContainerfileGenerator` can re-render from updated spec
- `BuildrootSpec` fields are mutable strings — easy to update

## Key Gap

GapDetector currently checks 6 dimensions but doesn't cover: source repo validity, git tag existence, or base image tag existence. These checks must be added for full node agent activation coverage.

## File Organization

New directory: `src/buildroot/agent/node_agents/` with `base.py` (NodeAgent base class), 10 node agent files, and `failure_agents.py`.

## Sources
- `src/buildroot/agent/claude_runner.py:33-136` (spawn_claude_agent)
- `src/buildroot/pipeline/orchestrator.py:78-229` (13-step pipeline)
- `src/buildroot/pipeline/gap_detector.py:16-199` (GapDetector)
- Issue #24 specification
