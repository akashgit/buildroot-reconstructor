---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-19
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-19

## Mode
Targeted — single hypothesis for issue #48 (agent system redesign)

## Context
- Current composite score: 0.632
- Weakest eval dimension: capability_surface (0.380)
- Last 3 experiments: #14 keep, #15 keep, #16 keep — 4 consecutive keeps
- Pipeline v2 (`pipeline_v2.py`) already implements the core issue #48 proposal (single analysis agent, repo clone, JAR download) but 13 features from the full spec are missing
- Issue #48 has 3 comment threads with 113 distinct requirements scattered across body and comments

## Approved Hypothesis

### H1: Create comprehensive agent system design issue synthesizing all 113 requirements from issue #48
- **Category:** EXPLORE
- **Priority:** High
- **Expected Impact:** No direct eval score change (design document, not code). Enables all subsequent pipeline experiments to be scoped correctly, prevents re-discovery of the 113 requirements, establishes fast-test-subset pattern (5.5 hours → 30 minutes iteration time).
- **Growth dimension:** capability_surface (new pipeline features enabled by the design document)

### Key Design Decisions
1. **v2 as starting point** — pipeline_v2.py already implements the core architecture; design builds ON v2, not from scratch
2. **All 113 requirements addressed** — organized into 10 categories (A-J) with explicit resolution status for each
3. **Exp #10 anti-pattern encoded as hard constraint** — ALL information passed to agents must be structured (not raw dumps), the single most important lesson (-19.4pp regression)
4. **8 implementation phases** — each independently testable:
   - Phase 1: PrePassFindings data model + run_prepass()
   - Phase 2: Analysis agent prompt + template_values_to_spec() converter
   - Phase 3: Feedback loop — elitist gate, dead-ends, rendered Containerfile, template-value diffs
   - Phase 4: Termination logic — stagnation, oscillation, double confirmation
   - Phase 5: Schema additions — module_path, artifact_path_pattern, build_tool_version
   - Phase 6: Multi-signal scoring fallbacks
   - Phase 7: Bug fixes (some superseded by design)
   - Phase 8: Migration — CLI flag, A/B benchmark, cleanup
5. **4-tier test plan:**
   - Tier 1: Unit tests (< 1 second, mocked, every commit)
   - Tier 2: Fast E2E smoke (7 minutes, jettison:1.5.4, after each phase merge)
   - Tier 3: Fast subset benchmark (~30 minutes, 7 packages covering all failure tiers, after milestones)
   - Tier 4: Full 31-package benchmark (~5.5 hours, once before declaring migration complete)

### 13 Specific v2 Gaps to Address
1. PrePassFindings structured data model (not raw dict)
2. attempted_but_failed tracking
3. Elitist gate with best-values feedback (not latest-values)
4. Dead-end tracking with {what_changed, from_value, to_value, result}
5. Rendered Containerfile in feedback context
6. Template-value diffs between iterations
7. Warm-start reverse-parse into template values
8. Cross-package knowledge transfer via RecipeStore
9. Multi-candidate variant generation (2-3 variants)
10. Full build log via file (agent reads with Read tool, not truncated)
11. Side-by-side unpacked JARs at L4
12. Double confirmation build
13. Parallel initial analysis + first build

## Anti-patterns to Avoid
- **Raw information dumps to agents (exp #10):** Single most costly mistake in project history. Every feedback channel must specify its structured format explicitly.
- **Ignoring v2 as the starting point:** v2 already implements the core architecture. Design must build on it.
- **Monolithic implementation:** 113 requirements require phased implementation with per-phase testing.
- **Testing only with mocked agents:** 498 unit tests in 0.1s is excellent for regression, insufficient for validation. Every phase needs Tier 2 E2E.
- **Full benchmark as the only validation:** 5.5 hours per run kills iteration speed. 7-package fast subset (~30 min) covers all failure tiers.

## CEO Verdict
**PROCEED** — Single hypothesis in targeted mode. H1 fully addresses the backlog item. Builder should create the GitHub issue comprehensive enough that a future Builder agent can implement any single phase without clarifying questions. Every one of the 113 requirements must appear in a checklist table.
