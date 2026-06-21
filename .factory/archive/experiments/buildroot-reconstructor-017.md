---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 17
verdict: KEEP
score_delta: 0.0000 (design document — score unchanged at 0.6321)
date: 2026-06-19
source: factory-archivist
---

# Experiment #017: Create comprehensive agent system v3 design issue

## Hypothesis
Create a comprehensive design issue (GitHub issue #51) synthesizing all 113 requirements from issue #48 (body + 3 comments), experiments #9-16, and the research context. The document should be complete enough that a future Builder agent can implement any single phase without clarifying questions.

## Result
**KEEP** — score unchanged at 0.6321 (design document, no code changes). Deliverable is GitHub issue #51: comprehensive Agent System v3 design with 113 requirements, 8 implementation phases, and 4-tier test plan. Score_before=0.6321, score_after=0.6321, Δ0.0000.

## What Changed

### Issue #51 — Agent System v3: Comprehensive Design Document
Created as a GitHub issue with 12 major sections (A-L):
- **A. Executive Summary** — problem, solution, expected impact (29% → 50%+ solve rate, $250 → $44/pkg cost, 55 min → 25 min time)
- **B. Architecture Diagram** — full pipeline flow from Maven coordinate to recipe cache
- **C. What Stays vs What Goes** — complete component inventory
- **D. Requirements Traceability Matrix** — all 113 requirements with status (implemented/phase/deferred/superseded)
- **E. Pre-Pass Design** — PrePassFindings data model with confidence, source, evidence per field
- **F. Scoring Design** — ScoreBreakdown, multi-signal fallback scoring
- **G. Feedback Loop Design** — elitist gate, dead-end tracking, structured feedback, stagnation/oscillation detection
- **H. Design Tension Resolutions** — 6 tensions resolved (structured vs raw feedback, pre-pass vs agent-only, etc.)
- **I. Schema Changes** — PrePassFindings, ScoreBreakdown, FailedApproach, TemplateValues extensions
- **J. Migration Path** — additive v1→v3 with rollback at every phase
- **K. 8 Implementation Phases** — each with files, dependencies, acceptance criteria
- **L. 4-Tier Test Plan** — unit (<1s) → smoke (7min) → fast subset (30min) → full benchmark (5.5hr)

### PR #52 — Design Issue Reference
- Single file: `.factory/strategy/design-issue-ref.md` (33 lines)
- Summary of the 8 implementation phases with key requirements per phase
- 4-tier test plan overview with fast subset packages identified
- Scope: reference doc only, zero code changes

### 8 Implementation Phases Defined
| Phase | Title | Key Scope |
|-------|-------|-----------|
| P1 | Data Models + Pre-Pass | PrePassFindings, schema extensions, run_prepass() |
| P2 | Analysis Agent Enhancement + Evaluator Bug Fix | Full tool access, enhanced prompts, diff_summary fix |
| P3 | Feedback Loop + Loop Control | Elitist gate, dead-end tracking, structured feedback |
| P4 | Multi-Signal Fallback Scoring | ScoreBreakdown, fallback signals, graceful degradation |
| P5 | CLI Integration + Pipeline Wiring | --pipeline v3 flag, batch support |
| P6 | Optimizations | Cross-package transfer, warm-start, parallel builds |
| P7 | Benchmark + Default Switch | Full 31-package benchmark, v3 becomes default |
| P8 | Cleanup Deprecated Components | Remove Observer, GapDetector, Node Agents, AnalyzeAgent |

### Key Hard Constraints Encoded
1. **Exp #10 anti-pattern**: ALL feedback must be structured — raw unstructured dumps cause -19.4pp regression
2. **Complete template values per iteration**: Every iteration must produce a complete set, not partial updates

## CEO Code Review
**CLEAN** — zero issues across all 7 dimensions:
- Correctness: PASS — 113 requirements in traceability matrix, architecture diagram complete, phases logically ordered
- Security: PASS — no code changes
- Edge cases: PASS — N/A for design document
- Missing tests: PASS — design itself defines the test plan
- Style & consistency: PASS — consistent formatting, requirement IDs A1-J6
- Scope compliance: PASS — PR #52 contains only `.factory/strategy/design-issue-ref.md`
- Guardrails: PASS — no source files modified

## Category
EXPLORE — design document, no code changes

## Links
- Project: buildroot-reconstructor
- Issue: #51 (design document)
- Issue: #50 (closed by PR #52)
- PR: #52 (OPEN)
- Branch: factory/exp-17-design-doc
- Source issue: #48 (agent system redesign spec)
- Strategy: `strategies/buildroot-reconstructor-2026-06-19-agent-system-design-issue.md`
