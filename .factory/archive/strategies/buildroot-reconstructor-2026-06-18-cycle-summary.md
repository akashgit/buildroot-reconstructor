---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-18
source: factory-archivist
---

# Cycle Summary: buildroot-reconstructor — 2026-06-18

## Cycle Profile
- **Run ID**: run-e8d140d9
- **Mode**: Targeted (single hypothesis from issue #42)
- **Issue**: #42 — Remove Builder agent, add controlled template modification to AnalyzeAgent
- **Experiment**: #015
- **Verdict**: KEEP
- **PR**: #43
- **Score**: 0.6814 → 0.6086 (-0.0728, intentional from code deletion)

## What Happened

This was a focused single-hypothesis cycle triggered by issue #42. Three parallel researchers confirmed the Builder agent was net-zero (7 improvements, 7 regressions across 363 iterations) and consumed 89% of iteration budget at $2-5 per opus call with zero L4 successes. The strategy was CEO-approved: delete Builder entirely, expand AnalyzeAgent with a 3-tier structured spec_overrides vocabulary channeled through template injection points.

### Research Phase
Three parallel researchers (local, external, context) all returned PROCEED verdicts:
- **Local**: Mapped all 11 files to modify, 6 injection points, identified `sanitize_gha_expressions()` relocation need and unreachable L4 error patterns
- **External**: Confirmed flat-template-with-conditionals as correct architecture (no Jinja2 inheritance), mapped every L4 failure type to a structured override key
- **Context**: Builder was net-zero across all experiments, AnalyzeAgent concept validated in exp 10 (failure was early termination, not the agent concept)

### Build Phase
Single builder agent shipped 17 files, +420/-854 lines:
- Deleted builder.py (594 lines)
- Added 3-tier spec_overrides (parameters, template selection, injection points)
- Fixed L4 classification bug (diff_summary never passed to classify_error)
- Added --legacy-builder CLI escape hatch
- Upgraded AnalyzeAgent to opus-4-6

### Review Phase
CEO code review passed first pass — all 6 dimensions clean. No issues found.

### Eval Phase
Score dropped -0.0728, entirely attributable to capability_surface reduction from deleting a 594-line module. No functional regression. Precheck override justified and documented.

## Cumulative Project Stats
- **Total Experiments**: 15 (IDs 1-10, 12-13, 15; #11 and #14 are keep-only operational fixes)
- **Decided**: 13 (12 KEEP, 1 REVERT)
- **Keep Rate**: 92.3%
- **Current Score**: 0.6086
- **Peak Score**: 0.8500 (experiments #001/#003)
- **Score from Inception**: 0.6433 → 0.6086 (−0.0347, but current architecture is fundamentally stronger)
- **Lines of Code**: Net negative this cycle (-434 lines) — architectural simplification

## Architectural State After This Cycle

The pipeline topology is now:
```
POM → Observer → AnalyzeAgent(spec_overrides) → Template(injection) → Build → Evaluate → loop
```

Builder agent is gone. The AnalyzeAgent controls all modifications through structured overrides:
- Tier 1: Parameters (jdk_minor_version, extra_build_flags, reproducibility_env, metadata_strip_patterns)
- Tier 2: Template selection (build_system, template_id)
- Tier 3: Injection points (pre_build_commands, post_build_commands, config_files, env_vars)

Key remaining gap: This cycle did not include E2E validation on rh-h100 nodes. The change is structural (Builder deletion + AnalyzeAgent expansion), and the eval confirmed no functional regression, but a real rebuild would further validate the new spec_overrides pathway.

## What's Next

The Builder removal opens the door for:
1. **E2E validation**: Run the spec_overrides pathway on real packages to confirm L4 improvements
2. **Tier 2/3 activation**: Template selection and injection points are wired but not yet exercised in production runs
3. **Score recovery**: capability_surface will recover as new spec_overrides features are exercised and validated
4. **Merge backlog**: PRs #43, #37, #33, #26, #21, #15 are all OPEN — merging the chain would consolidate the main branch
