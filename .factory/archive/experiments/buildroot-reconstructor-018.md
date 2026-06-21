---
tags:
  - factory
  - experiment
  - buildroot-reconstructor
project: buildroot-reconstructor
experiment_id: 18
verdict: keep
score_before: 0.6008
score_after: 0.9282
score_delta: +0.3274
date: 2026-06-19
source: factory-archivist
---

# Experiment #018: Agent System v3 — Full Implementation (Issue #51)

## Hypothesis
Implement the complete Agent System v3 as specified in issue #51 — 113 requirements across 8 phases — replacing the multi-agent node pipeline with a single Analysis Agent + structured feedback loop + multi-signal scoring.

## Result
**KEEP** — score changed from 0.6008 to 0.9282 (+0.3274). Largest single-experiment gain in project history.

## Review Pipeline
- **3 structured review iterations** (CEO code review): dimensions-based review across correctness, security, edge cases, tests, style, scope, guardrails
- **2 final review iterations**: post-fix verification of all resolved issues
- **7 issues found and fixed**: all issues resolved before verdict — CEO review CLEAN on final pass

## What Changed

PR #54 — 7 commits, +3066/-2833 lines across 40 files. 110 new unit tests (131 total passing after cleanup).

### Phase 1: Data Models + Pre-Pass (commit 350d8d1)
- `prepass.py` — PrePassFinding/PrePassFindings dataclasses, `run_prepass()` for deterministic data gathering
- `models.py` — FailedApproach model for dead-end tracking
- `models.py` — BuildrootSpec extensions: module_path, artifact_path_pattern, build_tool_version, jdk_minor_version, use_maven_wrapper

### Phase 2: Pipeline v3 Core + Evaluator Bug Fix (commit bcbe578)
- `pipeline_v3.py` — BUILDROOT_SCHEMA (20 fields), `_spec_to_dict`/`_dict_to_spec` converters, Analysis Agent config (claude-opus-4-6, full tool access, 30 turns/900s), enhanced system prompt with 6-step investigation strategy and evidence hierarchy
- `evaluator.py` — Fixed diff_summary dead code (A1 bug): `.details`→`.diff`, `.missing_files`→`.missing`, `.extra_files`→`.extra`, `.differing_keys`→`manifest_diff_keys`, `.divergent_classes`→`classes_divergent`

### Phase 3: Feedback Context Builder (commit ca5cc1d)
- `feedback.py` — `build_feedback_context()` producing structured summaries + file paths with explicit Read instructions
- Template-value diffs, elitist gate (revert on regression), dead-end tracking (FailedApproach list)
- Stagnation detection (2 consecutive identical hash+reward), oscillation detection (A-B-A pattern)
- Double confirmation (2 builds both >= 0.98), rendered Containerfile in feedback, score history table, level-specific diagnosis guides

### Phase 4: Multi-Signal Fallback Scorer (commit c0a823a)
- `scorer.py` — ScoreBreakdown dataclass, `compute_fallback_score()` (weighted: bytecode 0.40 + manifest 0.30 + unit_tests 0.30)
- `check_bytecode_version_match` (reads .class bytes 6-7), `check_manifest_sanity` (MANIFEST.MF + pom.properties GAV)
- `evaluator.py` — `l4_fallback_signals()` for packages without original JARs
- `pipeline_v3.py` — `fallback_ceiling_reached` and `l3_ceiling` termination conditions

### Phase 5: CLI Integration + Pipeline Wiring (commit 28d40cf)
- `--pipeline v3` CLI flag and `--batch` option for batch processing
- Wired v3 pipeline into `run_inner_loop()` via pipeline parameter
- `packages_fast_iteration.txt` — 3 benchmark packages (json-path, junit, commons-fileupload)
- Default remains v1 — zero regression risk

### Phase 6: Optimizations (commit e99a2c5)
- `RecipeStore.get_group_hints()` — query solved recipes for same-group artifacts (cross-package transfer)
- `reverse_parse_containerfile()` — extract template values from existing Containerfile (warm-start)
- Parallel first build: evaluate pre-pass fallback while analysis agent runs
- Multi-variant elitist: agent outputs 1-3 variants, incumbent always slot 0, build all in parallel, pick winner — incumbent survives if all regress
- Warm-start: `--resume` with v3 pipeline reverse-parses Containerfile into template values and starts in feedback mode

### Phase 7: Benchmark (deferred)
- 3-package benchmark file created but E2E execution deferred to rh-h100-01 operational step

### Phase 8: Cleanup (commit b45a947)
- 2829 lines of deprecated code removed across 26 files
- Deleted: `augmented_observer.py`, `gap_detector.py`, `node_agents/` directory (11 agents)
- Removed: ProgressSignal, AnalyzeAgent (v2), classify_error, _suggest_fix, build_remediation_context, ANALYZE_AGENT_SCHEMA, ANALYZE_AGENT_SYSTEM

## CEO Code Review
**CLEAN** — passed after 3 structured review iterations + 2 final review iterations:
- 7 issues found and fixed across iterations
- Final pass: all 7 dimensions PASS
- Correctness: PASS
- Security: PASS
- Edge cases: PASS
- Missing tests: PASS (131 tests passing after cleanup)
- Style: PASS
- Scope: PASS — All 8 phases addressed (P7 is execution, handled separately)
- Guardrails: PASS

## Key Design Decisions
1. **Single Analysis Agent** replaces 11 node-scoped agents + AnalyzeAgent — fewer LLM calls per iteration, richer context per call
2. **Structured schema** (BUILDROOT_SCHEMA, 20 fields) replaces free-form Containerfile rewriting — agent modifies values, template renders
3. **Multi-signal fallback scoring** enables progress measurement even without original JAR (bytecode + manifest + unit_test signals)
4. **Cross-package transfer** via RecipeStore — solved recipes inform same-group artifacts
5. **Multi-variant elitist** — agent proposes 1-3 variants per iteration, all built in parallel, incumbent always survives if all regress

## Stats
- New code: 3050 lines across 16 files
- Deleted code: 2829 lines across 26 files (net: +233 lines)
- New tests: 110 unit tests
- Total tests: 131 passing after cleanup
- Changed files: 40

## Links
- Project: buildroot-reconstructor
- Issue: #51 (Agent System v3 design), #53 (implementation task)
- PR: #54
- Strategy: `strategies/buildroot-reconstructor-2026-06-19-agent-system-v3-implementation.md`
- Design doc: Issue #51 (12000+ words, 113 requirements, 8 phases)
- Prior art: Exp #010 (agent architecture, REVERTED), #012 (elitist gate, KEPT), #013 (critique fixes, KEPT), #015 (Builder removal, KEPT)
