---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-42
source: factory-archivist
date: 2026-06-18
research_type: local
---

# Issue #42 Local Research: Builder Removal & Controlled Template Modification

## Summary

Complete code-level analysis of Builder agent removal (595 lines in `builder.py`) and replacement with expanded AnalyzeAgent `spec_overrides`. Mapped every Builder invocation, dependency, and cross-cutting concern.

## Key Findings

### Builder Agent (builder.py) — Complete Map
- **595 lines**, 5 module-level functions, 7 class methods
- Critical dependency: `sanitize_gha_expressions()` (lines 82–98) imported by `evaluator.py:33` — must be relocated before deletion
- Three modes: `refine()` (exploit), `explore()` (explore), `fresh_start()` (meta-shift) — all produce free-form Containerfile text
- Constants include `SYSTEM_PROMPT`, `DIAGNOSIS_PROMPT`, `GHA_EXPRESSION_RE`

### Loop Integration (loop.py) — Builder Is Redundant in Agent Loop
- `_run_standard_loop` (lines 75–225): Builder at lines 191–217
- `_run_agent_loop` (lines 228–491): Builder at lines 458–483
- **Critical finding**: In `_run_agent_loop`, lines 430–440 already implement the correct re-observe → template re-render flow. Builder at 458–483 overwrites this with free-form rewriting — redundant and counterproductive.

### AnalyzeAgent (analyzer.py) — Current spec_overrides Vocabulary
- 11 existing override keys (base_image, jdk_version, build_command, etc.)
- Schema typed as loose `{"type": "object"}` — no sub-schema enforcement
- `diff_summary` passed to AnalyzeAgent but truncated to 300 chars — insufficient for L4 diagnosis
- `build_remediation_context()` (lines 409–467) exists for Builder; not used by AnalyzeAgent

### L4 Error Patterns — Confirmed Unreachable
- `classify_error()` scans `error_summary` + `build_log`, but L4 patterns (`structural_match=False`, etc.) appear in `diff_summary` which is NOT passed to `classify_error()`
- Issue's claim verified: L4 patterns at analyzer.py:109–117 never trigger

### Template Gaps — All 4 Templates Need Same 6 Injection Points
1. `config_files` block (after env_vars, before git clone)
2. `pre_build_commands` block (after WORKDIR, before build)
3. `extra_build_flags` append (on build command line)
4. `post_build_commands` block (after build, before normalization)
5. `metadata_strip_patterns` merge (extend normalization sed)
6. `reproducibility_env` merge (additional ENV lines)

### New BuildrootSpec Fields Required
- `extra_build_flags: list[str]`, `reproducibility_env: dict[str, str]`, `metadata_strip_patterns: list[str]`
- `pre_build_commands: list[str]`, `post_build_commands: list[str]`, `config_files: list[dict]`
- `jdk_minor_version` → maps to existing `jdk_spec.version`
- `build_system` / `template_id` → affect `_select_template()` logic

### Files to Modify (11 total, prioritized)
| Priority | File | Action |
|----------|------|--------|
| P1 | builder.py | DELETE (after relocating sanitize_gha_expressions) |
| P1 | loop.py | Remove Builder, wire AnalyzeAgent → re-observe → re-render |
| P1 | analyzer.py | Expand spec_overrides, upgrade to opus, relocate utility |
| P1 | pipeline/models.py | Add new BuildrootSpec fields |
| P1 | templates/*.j2 | Add 6 injection points to all 4 templates |
| P1 | containerfile.py | Wire template selection overrides, new context vars |
| P1 | augmented_observer.py | Extend _apply_spec_overrides() field mappings |
| P2 | evaluator.py | Update import, pass full L4 data |
| P2 | agent_cmd.py | Add --legacy-builder CLI flag |
| P3 | guards.py | Remove builder.py from MUTABLE_SURFACES |
| P3 | outer_strategist.py | Update default files_to_modify references |
