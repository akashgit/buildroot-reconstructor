---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-19
---

# Issue #51 Context Research: Implementation Scope & Benchmark Requirements

## Source

GitHub Issue #51 — Agent System v3: Comprehensive Design Document. Synthesized from issue #48 (body + 3 comments), experiments #9-16, and 113 requirements in 10 categories (A-J). Created as experiment #17 (KEEP, design-only).

## 8 Implementation Phases

### P1: Data Models + Pre-Pass (16 requirements)
- Create `prepass.py` with `run_prepass()`, `PrePassFinding`, `PrePassFindings`
- Add `FailedApproach` dataclass to models
- Add `module_path`, `artifact_path_pattern`, `build_tool_version` to `BuildrootSpec`
- Pre-download AND pre-extract original JAR
- Data-gathering only — no rendering, no spec decisions

### P2: Analysis Agent Enhancement + Evaluator Bug Fix (8 requirements)
- Fix diff_summary dead code (evaluator.py:162-175)
- Flip tool access: current AnalyzeAgent blocks ALL tools — v3 needs full access
- Increase budget: 30 turns/$10/900s (from 3/$2/300s)
- Enhanced system prompt: evidence hierarchy, critical rules, 6-step investigation

### P3: Feedback Loop + Loop Control (18 requirements)
- `build_feedback_context()`: structured summaries + file paths (NEVER raw dumps — exp #10 lesson)
- Elitist gate: on regression, revert to best values
- Stagnation detection: 2 consecutive identical (values hash + reward)
- Oscillation detection: A-B-A pattern on template value hashes
- Double confirmation: 2 builds, both >= 0.98
- Template-value diffs, rendered Containerfile in feedback, both JARs unpacked at L4

### P4: Multi-Signal Fallback Scoring (12 requirements)
- `ScoreBreakdown` dataclass, `_compute_fallback_score()`
- 3 fallback signals: bytecode_version_match (0.40), manifest_sanity (0.30), unit_tests_pass (0.30)
- Fix Bug A2: no-JAR dead loop termination
- New termination: fallback_ceiling_reached, l3_ceiling

### P5: CLI Integration (2 requirements)
- `--pipeline v3` CLI flag, default remains v1 until P7

### P6: Optimizations (5 requirements)
- Cross-package `get_group_hints()`, warm-start reverse-parse, parallel first build, multi-variant elitist

### P7: Benchmark (1 requirement) — Full 31-package, make v3 default if >= v1
### P8: Cleanup (5 requirements) — Remove Observer, AgentAugmentedObserver, GapDetector, Node Agents

## Phase Dependencies
Strictly sequential: P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8. Additive design means v1 remains default until P7 — zero regression risk during P1-P6.

## 3-Package Benchmark

| Package | Current Level | Current Reward | Failure Class |
|---------|--------------|----------------|---------------|
| `com.jayway.jsonpath:json-path:2.9.0` | L2 | 0.15 | wrong_build_system (Gradle misidentified as Maven) |
| `junit:junit:4.13.2` | L3 | 0.50 | plugin/configuration_error + multi-level progression |
| `commons-fileupload:commons-fileupload:1.5` | L3 | 0.50 | L3 stagnation (stuck 14 iterations) |

File `results/packages_fast_iteration.txt` must be created. Runtime: ~15 min, capped at 5 iterations/package.

## What "Scoring .9" Requires

Reward formula: `reward = 0.05*L1 + 0.10*L2 + 0.35*L3 + l4_score*0.50`

Achieving reward >= 0.9 requires reaching L4 with l4_score >= 0.80. Current packages score 0.15-0.50. This is a high bar — none of the 3 benchmark packages is close to 0.9 today.

## Prior Experiment Lessons

| Experiment | Lesson | Impact on v3 |
|-----------|--------|-------------|
| #10 (REVERT, -19.4pp) | Raw unstructured dumps cause catastrophic regression | Hard Constraint F1: ALL feedback structured summaries + file paths |
| #10 | 3-iteration early termination is too aggressive | Stagnation uses both value hashes AND rewards; max_iterations=10 |
| #12 (KEEP, +0.025) | Elitist gate prevents regression | P3 implements elitist gate with patience counter |
| #13 (KEEP, +0.290) | Targeted pipeline fixes beat broad rewrites | Scoped, well-targeted improvements preferred |
| #15 (KEEP, -0.073) | Complete template values per iteration is correct | Hard Constraint F2: agent outputs COMPLETE values every iteration |
| #16 (KEEP, 0.000) | `build_remediation_context()` had zero call sites | P3 replaces entirely with richer `build_feedback_context()` |

## Key Constraints from Memory

1. **E2E mandatory**: After ANY agent/pipeline code change, real E2E on >= 1 package MUST happen. Mocked tests insufficient. Token cost not a valid skip reason.
2. **Discuss design changes first**: Never change pipeline architecture without discussing with Akash.
