---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-45
source: factory-archivist
date: 2026-06-18
---

# Issue #45 Local Analysis: Diagnostic Feedback Loop Disconnections

## Summary

File-by-file analysis of the information flow gap between the pipeline's diagnostic machinery and the components that should act on it. Six disconnections identified across 7 subsystems.

## Key Findings

### 1. `build_remediation_context()` — Defined But Never Called
- **Location**: `analyzer.py:430-488`
- **Status**: Complete implementation with zero call sites (confirmed by grep)
- Produces structured markdown with: build progress, progress delta, root cause details, fix direction, relaxation flags, key error lines, loop detection
- All supporting functions (`estimate_build_progress`, `extract_root_cause_details`, `compute_progress_delta`, `suggest_relaxation_flags`, `detect_error_loop`, `extract_build_log_excerpt`) are fully implemented and operational

### 2. No Cross-Iteration Error State Tracking
- Neither `_run_standard_loop` (line 77) nor `_run_agent_loop` (line 292) maintain:
  - `error_history: list[str]` — needed for `detect_error_loop()`
  - `previous_progress: BuildProgress` — needed for `compute_progress_delta()`
- Both are required parameters for `build_remediation_context()`

### 3. AnalyzeAgent Prompt Missing Diagnostic Context
- `analyze_cycle()` at lines 696-749 receives truncated build results but NOT:
  - Remediation context from local analyzer
  - Build progress trajectory
  - Error loop warnings
- Needs `remediation_context: str = ""` parameter and `{remediation_section}` in task prompt

### 4. Node Agents Have Zero Build Error Awareness
- `observe_top_k()` passes only `context={"containerfile": draft_containerfile}` to node agents
- No `build_error_context` parameter exists on `observe()` or `observe_top_k()`
- Agents that would benefit most: TemplateAgent, BuildCmdAgent, JDKAgent, ImageAgent

### 5. SOURCE_DATE_EPOCH Template Ordering Bug
- All 4 templates: hardcoded `ENV SOURCE_DATE_EPOCH=946684800` appears AFTER `reproducibility_env` block
- Docker `ENV` last-write-wins means AnalyzeAgent's `reproducibility_env` overrides are silently ignored
- Fix: move default into `containerfile.py._build_template_context()`, delete hardcoded lines from templates

### 6. TemplateAgent Fix Vocabulary Too Narrow
- Only 3 fix types: `fix_from:`, `fix_workdir:`, `fix_build_cmd:`
- Missing: `fix_env:KEY=VALUE`, `fix_flag:FLAG`, `fix_remove_flag:PREFIX`
- Without these, TemplateAgent cannot act on environment or flag errors even when it receives error context

## Disconnection Map

| From | To | Gap |
|---|---|---|
| `analyzer.analyze()` → `AnalysisResult` | `build_remediation_context()` | Never called |
| `build_remediation_context()` output | `AnalyzeAgent.analyze_cycle()` | No parameter exists |
| Loop error state | `observer.observe_top_k()` | No parameter exists |
| `observer.observe_top_k()` | Node agents `_build_task()` | Context dict missing error info |
| AnalyzeAgent `reproducibility_env` override | Templates | Hardcoded ENV overwrites override |
| TemplateAgent error awareness | `_apply_candidate()` | Only 3 fix types |

## Implementation Estimate
~120 lines across 6 subsystems. All changes within mutable_surfaces.
