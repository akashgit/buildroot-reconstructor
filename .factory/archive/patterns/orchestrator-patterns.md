---
tags:
  - factory
  - patterns
  - orchestrator
source: factory-archivist
date: 2026-06-21
---

# Cross-Project Pattern: Agent-as-Orchestrator

## Pattern Discovery
Discovered in buildroot-reconstructor experiment #019 (2026-06-21)

## Pattern Description

**Monitor-Until-Threshold-Then-Takeover**: An outer-loop agent monitors a deterministic pipeline (or weaker agent) for N iterations. When progress stalls (e.g., 3 consecutive iterations below threshold), the orchestrator takes over with domain expertise and knowledge base context.

### Why This Works

1. **Cost efficiency**: Cheap pipeline handles easy cases (90% of packages)
2. **Expert intervention**: Expensive orchestrator only invoked for hard cases (10% of packages)
3. **Knowledge accumulation**: Orchestrator learnings persist in KB, making pipeline smarter over time
4. **No regression risk**: Pipeline always runs first, orchestrator is additive

### Implementation Details (Buildroot)

- **Pipeline**: v3 agent loop with elitist gate, multi-variant eval (15 iterations, ~$2-5 per package)
- **Threshold**: 3 consecutive stalled iterations (reward plateau or oscillation)
- **Orchestrator**: Claude Code agent spawned via Python subprocess with:
  - Three-tier system prompt (domain + build system + package-specific)
  - KB query results (ranked by exact tag > partial > group > text similarity)
  - Full comparison report from last pipeline iteration
- **Learning**: Winning Containerfiles auto-recorded as KB templates post-solve

### Quantitative Evidence

| Metric | Pipeline Only (v3) | With Orchestrator (v4) | Improvement |
|--------|-------------------|----------------------|-------------|
| L4 solve rate | 29.0% (9/31) | 32.3% (10/31) | +3.3pp |
| json-path:2.9.0 | L1 (stuck) | L4 (0.9993) | L1 → L4 |
| protobuf-java:3.25.2 | L0 (no compile) | L2 (first compile) | L0 → L2 |
| Cost per solve (json-path) | N/A (never solved) | $0.25 | Baseline |
| Time per solve (json-path) | N/A | 591s | <10 min |

### When to Apply

**Good fit:**
- Task has easy cases solvable by cheap heuristic + hard cases needing expert reasoning
- Domain knowledge can be encoded and accumulated (KB)
- Progress is measurable at each iteration (enables threshold detection)
- Orchestrator cost justified only for hard cases

**Poor fit:**
- All cases equally hard (no threshold to detect)
- No domain knowledge to encode (orchestrator has no advantage over pipeline)
- Real-time latency requirements (orchestrator adds overhead)

## Related Patterns

- **Tiered fallback** (exp #018, pipeline_v3.py): Multi-signal scoring with ceiling detection — complementary to orchestrator (pipeline uses it, orchestrator benefits from it)
- **Elitist gate** (exp #012): Checkpoint-and-restore for stochastic optimizers — prerequisite for orchestrator (prevents premature termination)
- **Knowledge base evolution** (ACE, cognitive architectures): KB grows from winning strategies — orchestrator is consumer and producer

## Cross-Project Applicability

This pattern should work for:
- **Code migration**: Simple AST transforms (cheap) + complex refactors (orchestrator)
- **Test generation**: Template-based tests (cheap) + edge case tests (orchestrator)
- **Bug localization**: Static analysis (cheap) + dynamic tracing (orchestrator)
- **Configuration optimization**: Grid search (cheap) + Bayesian optimization (orchestrator)

**Key requirement**: The task must have a natural two-tier structure (easy/hard) and a measurable progress signal.

## Archive Metadata
- **Source experiment**: buildroot-reconstructor #019
- **Pattern type**: Architecture (outer loop coordination)
- **Evidence strength**: Strong (quantitative solve rate improvement, cost reduction)
- **Replication status**: Not yet replicated (single project so far)
