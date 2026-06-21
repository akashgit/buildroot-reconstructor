---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-15
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-15 (Builder Complete)

## State
Builder phase COMPLETE for experiment #009. CEO code review: CLEAN. Benchmark on rh-h100-01 pending.

## What Was Built
13 Claude Code reviewer agents (10 node-scoped + 3 post-build failure agents) integrated into the deterministic pipeline via AgentAugmentedObserver.

### Node Agents (Sonnet model, $2/agent budget, 300s timeout)
| # | Agent | Field | Impact | Always Active |
|---|-------|-------|--------|---------------|
| 1 | PomAgent | pom_data | Relocation & sparse POM detection | Yes |
| 2 | ParentChainAgent | parent_chain | Missing parents, BOM imports | Yes |
| 3 | PropertyAgent | properties | Resolve remaining `${...}` placeholders | No |
| 4 | RepoAgent | source_repo | URL validation, multi-module subdirs | Yes |
| 5 | CIAgent | build_command | Workflow selection, alternative CI | No |
| 6 | JdkAgent | jdk_version | Cross-reference POM/CI/.java-version/manifest | No |
| 7 | ImageAgent | base_image | Docker Hub tag verification | Yes |
| 8 | TagAgent | git_tag | `git ls-remote` verification | No |
| 9 | BuildCmdAgent | build_command | Maven vs Gradle detection | No |
| 10 | TemplateAgent | containerfile | Syntax validation, placeholder detection | Yes |

### Failure Agents (Opus model, $3/agent budget, 300s timeout)
| Agent | Trigger | Fix Types |
|-------|---------|-----------|
| L2FailureAgent | Container build fails | base_image, system_package, git_tag |
| L3FailureAgent | No JAR in target/ | build_command, workdir, env_var |
| L4FailureAgent | JAR mismatch | build_command, env_var |

## Architecture
```
Observer.observe(coordinate)
  → BuildrootSpec + draft Containerfile
  → GapDetector.analyze(spec)
  → For each node agent: should_activate(gaps) → review(spec) → apply_best(spec, candidates)
  → Re-render Containerfile from updated spec
  → Inner loop iteration 0: if level < 4, run failure agent → apply fixes → re-render
```

## Key Design Decisions
1. Evidence hierarchy ranking (6 tiers) instead of self-assessed confidence scores
2. Sonnet for node agents (cost-conscious) / Opus for failure agents (reasoning depth)
3. 5 agents always activate regardless of gap status (POM, ParentChain, Repo, Image, Template)
4. Failure agents fire only on iteration 0 to prevent cascading failures
5. No unit tests — project conventions require real E2E benchmark, not mocked agent tests

## Next Step
Full 31-package benchmark on rh-h100-01:
```bash
python -m buildroot agent --batch results/packages_benchmark.txt --host rh-h100-01 --output results/benchmark-agents/ --node-agents --max-iterations 15
```
Compare against baseline: 4/31 L4 (13%).

## PR
#26 — +1397/-3, 17 files, branch `exp9-node-agents`
