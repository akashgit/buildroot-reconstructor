---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-13
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-13 (Agentic Inner Loop)

## CEO Verdict: PROCEED — PLAN APPROVED

### Strategy Decision
Single hypothesis approved in targeted mode: **H1 — Implement Agentic Reconstructor Inner Loop MVP with Outer Loop Skeleton** (EXPLORE/mixed, capability_surface growth, issue #13).

### Rationale
The one-shot pipeline has plateaued at 50% L4 reproducibility (5/10 EQUIVALENT). All 5 DIVERGENT packages fail for fixable reasons (GHA secrets, wrong JDK, multi-module builds, wrong git tag) that an iterative loop could self-correct. This is the single largest capability jump available — from static inference to iterative self-correction.

### Design Space Assessment
| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | L1-L4 pipeline, PNC validation, JAR comparison all built |
| Bug fixes | 4 | 5 kept experiments, all bugfix-adjacent |
| Instrumentation | 1 | 35% observability, 13% function coverage |
| Flow changes | 1 | Still one-shot pipeline — no iteration |
| New agents | 0 | No agentic capabilities exist yet |
| Prompt engineering | 0 | No LLM integration |
| Eval improvements | 3 | eval/score.py exists |
| Knowledge management | 1 | No structured failure taxonomy |
| Infrastructure | 3 | SSH builds on rh-h100-01 work |
| Operational execution | 3 | 5/10 EQUIVALENT, 0.5833 PNC accuracy |
| Self-evolution | 0 | No meta-learning |

**Underserved dimensions targeted:** New agents (0→0.6), Flow changes (1→iterative), Prompt engineering (0→LLM-driven mutation).

### Hypothesis H1: Agentic Reconstructor Inner Loop MVP

**Category:** EXPLORE | **Type:** mixed | **Growth:** capability_surface

**Implementation scope (9 new modules + tests):**
1. `agent/models.py` — BuildAttempt, DeadEndEntry, EvalResult, ProgressSignal (AdaEvolve G_t signal)
2. `agent/observer.py` — Wraps existing orchestrator for initial spec generation
3. `agent/builder.py` — LLM-driven Containerfile mutation via AnthropicVertex (exploit/explore/meta-shift modes)
4. `agent/evaluator.py` — 4-level scoring (L1 parse → L2 build → L3 build-cmd → L4 JAR comparison)
5. `agent/analyzer.py` — Error classification + dead-end registry (2-failure threshold)
6. `agent/loop.py` — Inner loop orchestrator (max 15 iterations, G_t mode switching)
7. `cli/commands/agent_cmd.py` — CLI entry point
8. `agent/outer_loop.py` — Outer loop skeleton (batch harness, no strategy evolution yet)
9. Unit tests for all modules

**Execution steps:**
1. Run unit tests: `pytest tests/test_agent*.py -v`
2. Inner loop on commons-lang3 (known EQUIVALENT): `python -m buildroot agent org.apache.commons:commons-lang3:3.14.0 --host rh-h100-01`
3. Outer loop on 3 packages: `python -m buildroot agent --batch packages_smoke.txt --host rh-h100-01 --output results/agent-smoke/`
4. Verify: commons-lang3 should pass L4, micrometer-core should iterate, spring-security-core regression check

**Expected impact:**
- capability_surface: 0.0 → 0.6
- experiment_diversity: +0.1
- L4 reproducibility: 50% → 70%+

### Anti-Patterns Documented
- No PUCT in Phase 1 — simple approaches succeed first
- GHA expression sanitization is pre-flight, not agent-learned
- Must use `AnthropicVertex(region='us-east5', project_id='itpc-gcp-ai-eng-claude')`, not direct anthropic SDK
- Phase 1 skips: Researcher agent, evolve-block markers, PUCT checkpoint selection, strategy evolution

### CEO Notes for Builder
- Large implementation (9 new files + tests). Builder timeout: 1800s.
- Builder MUST implement the execution step — code-only completion is a failure for mixed hypotheses.
- GHA expression sanitization is pre-flight: hard-code regex strips.
- Outer loop skeleton is a harness only — no Failure Analyst, Researcher, or Strategy evolution yet.
- Build execution is SSH-based: `ssh rh-h100-01 "podman build ..."` — handle SSH subprocess management.

### Research Grounding
Validated by 6 external papers/systems:
- RepairAgent (ICSE 2025) — LLM as autonomous repair agent
- AprMcts (2025) — MCTS for program repair, UCT C=0.7
- SWE-Search (ICLR 2025) — 3-agent architecture maps to Builder/Evaluator/Analyzer
- SGAgent — Multi-agent repair with escalation
- CI-Repair-Bench — 18.9% single-shot rate confirms iterative approach essential
- AdaEvolve — G_t exponential-decay signal for mode switching

### Context
- Pre-experiment score: 0.8243
- Keep streak: 5/5
- Previous cycle: #005 KEEP — PNC validation execution, 0.5833 mean accuracy
- Pattern: Plateau at 50% L4. Feedback loop is the single lever for next capability jump.
