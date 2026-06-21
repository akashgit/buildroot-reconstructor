# Research Context: Issue #51 Implementation

## Source: GitHub Issue #51 — Agent System v3: Comprehensive Design Document

Issue #51 is the definitive implementation specification for the v3 agent pipeline, synthesized from issue #48 (body + 3 comments), experiments #9-16, and 113 requirements in 10 categories (A-J). It was created as experiment #17 (KEEP, design-only).

---

## Full Scope — 8 Implementation Phases

### Phase 1 (P1): Data Models + Pre-Pass
**Scope:** 16 requirements (E1-E9, I1-I4, D9, D12, D16)

**Files to create:**
- `src/buildroot/agent/prepass.py` — `run_prepass()`, `PrePassFinding`, `PrePassFindings`

**Files to modify:**
- `src/buildroot/agent/models.py` — Add `FailedApproach` dataclass
- `src/buildroot/agent/pipeline_v2.py` — Add `module_path`, `artifact_path_pattern`, `build_tool_version` to `BUILDROOT_SCHEMA`; update `_spec_to_dict()` and `_dict_to_spec()`
- `src/buildroot/pipeline/models.py` — Add new fields to `BuildrootSpec`

**Tests to create:**
- `tests/test_prepass.py`

**Key data models:**
- `PrePassFinding(value, source, confidence, evidence)` — per-field structured finding
- `PrePassFindings` — 11 finding fields + `pom_data`, `ci_data`, `attempted_but_failed`, artifact paths
- `FailedApproach(what_changed, from_value, to_value, result, why_it_failed, iteration)`

**Acceptance criteria:**
- PrePassFinding/PrePassFindings dataclasses with all fields from E2-E6
- `run_prepass()` calls existing POM parser, Maven Central fetcher, GitHub API, CI parser
- Populates `attempted_but_failed` for failed lookups
- Pre-pass is data-gathering only (E7) — no rendering, no spec decisions
- BUILDROOT_SCHEMA includes new fields; converters handle them
- JAR pre-downloaded AND pre-extracted (manifest + bytecode version available)
- Unit tests cover construction and conversion

**Dependencies:** None (first phase)

---

### Phase 2 (P2): Analysis Agent Enhancement + Evaluator Bug Fix
**Scope:** 8 requirements (A1, D1, D3, D5, D6, D7, D13, J2)

**Files to modify:**
- `src/buildroot/agent/evaluator.py` — Fix dead code at lines 162-175 (`.diff` not `.details`, `.missing` not `.missing_files`)
- `src/buildroot/agent/pipeline_v2.py` — Enhanced system prompt, full tool access, increased budgets

**Tests to create:**
- `tests/test_evaluator_diff_summary.py`

**Key changes:**
- Full tool access: `["Bash", "Read", "WebSearch", "WebFetch", "Agent"]`
- Initial budget: 30 turns, $10.0, 900s (up from 20/5.0/600s)
- System prompt: evidence hierarchy, critical rules (Apache flags, GPG skip, SOURCE_DATE_EPOCH), Maven wrapper as template field
- Investigation strategy expanded to 6 steps

**Acceptance criteria:**
- diff_summary correctly extracts missing files, extra files, differing manifest keys, divergent classes
- Full tool access, increased budgets
- System prompt includes evidence hierarchy, critical rules
- Unit tests verify diff_summary extraction
- Existing tests still pass

**Dependencies:** Phase 1

---

### Phase 3 (P3): Feedback Loop + Loop Control
**Scope:** 18 requirements (G1-G11, G13, H5, H6, H8, D10, D17, A4)

**Files to create:**
- `src/buildroot/agent/feedback.py` — `build_feedback_context()`, template-value diff, dead-end tracking

**Files to modify:**
- `src/buildroot/agent/pipeline_v2.py` — Replace `_run_failure_agent()` with enhanced feedback loop
- `src/buildroot/agent/models.py` — Wire `FailedApproach` from P1

**Tests to create:**
- `tests/test_feedback.py`

**Key features:**
- **Elitist gate:** On regression → revert to best values, warn agent
- **Dead-end tracking:** `FailedApproach` list maintained across iterations
- **Stagnation detection:** 2 consecutive identical (values hash + reward)
- **Oscillation detection:** A-B-A pattern on template value hashes
- **Double confirmation:** 2 builds, both >= 0.98
- **Structured feedback:** Summary in prompt + file paths for full artifacts + explicit Read instructions
- **Rendered Containerfile** included in feedback
- **Template-value diffs** showing what changed iter N → N+1
- **Both JARs unpacked** at L4 for side-by-side diff

**Acceptance criteria:**
- `build_feedback_context()` produces structured summary + file paths
- All feedback features listed above are implemented
- Unit tests cover all feedback construction, stagnation, oscillation, elitist gate

**Dependencies:** Phase 1 (FailedApproach model), Phase 2 (fixed diff_summary)

---

### Phase 4 (P4): Multi-Signal Fallback Scoring
**Scope:** 12 requirements (F1-F7, A2, H3, H4, J4)

**Files to create:**
- `src/buildroot/agent/scorer.py` — `ScoreBreakdown`, `build_score_breakdown()`, `_compute_fallback_score()`

**Files to modify:**
- `src/buildroot/agent/evaluator.py` — Add `_l4_fallback_signals()`
- `src/buildroot/agent/pipeline_v2.py` — Integrate ScoreBreakdown, add termination conditions

**Tests to create:**
- `tests/test_scorer.py`

**Fallback signals (when no original JAR available):**
- `bytecode_version_match` (weight 0.40) — .class major version vs declared JDK
- `manifest_sanity` (weight 0.30) — MANIFEST.MF + pom.properties GAV check
- `unit_tests_pass` (weight 0.30) — mvn test inside same container

**New termination conditions:**
- `fallback_ceiling_reached`: fallback signals + reward >= 0.85 + stagnation >= 2
- `l3_ceiling`: no JAR + no fallback signals (fixes Bug A2: no-JAR dead loop)

**Dependencies:** Phase 3

---

### Phase 5 (P5): CLI Integration + Pipeline Wiring
**Scope:** 2 requirements (J3, B10)

**Files to modify:**
- `src/buildroot/agent/loop.py` — Add `pipeline: str` parameter ("v1", "v3")
- `src/buildroot/cli/commands/agent_cmd.py` — Add `--pipeline v3` CLI flag
- `src/buildroot/agent/outer_loop.py` — Support `pipeline` parameter in batch runs

**Key behavior:**
- `buildroot agent COORDINATE --pipeline v3` runs v3
- Default remains v1 until Phase 7
- Batch runs support `--pipeline v3`

**Dependencies:** Phases 1-4

---

### Phase 6 (P6): Optimizations
**Scope:** 5 requirements (D8, D15, G12, G14, H9)

**Key features:**
- **Cross-package knowledge transfer:** RecipeStore `get_group_hints()` for same-group artifacts
- **Warm-start reverse-parse:** Containerfile → template values (regex-first, LLM fallback)
- **Parallel first build:** Observer draft build + Analysis Agent run concurrently
- **Multi-variant elitist invariant:** Agent produces K-1 variants, system prepends current best as variant[0]

**Dependencies:** Phase 5

---

### Phase 7 (P7): Benchmark + Default Switch
**Scope:** 1 requirement (J5)

Run full 31-package benchmark. If v3 solve rate >= v1 (currently 29%) with no regressions on 9 solved packages → make v3 the default.

**Dependencies:** Phase 6

---

### Phase 8 (P8): Cleanup Deprecated Components
**Scope:** 5 requirements (C3, C4, C6, C8, J6)

Remove Observer (keep what prepass needs), AgentAugmentedObserver, GapDetector, 11 Node Agents, AnalyzeAgent class, ProgressSignal.

**Dependencies:** Phase 7

---

## Phase Dependencies (Critical Path)

```
P1 (Data Models + Pre-Pass)
 └─► P2 (Agent Enhancement + Evaluator Fix)
      └─► P3 (Feedback Loop + Loop Control)
           └─► P4 (Multi-Signal Scoring)
                └─► P5 (CLI Integration)
                     └─► P6 (Optimizations)
                          └─► P7 (Benchmark)
                               └─► P8 (Cleanup)
```

Phases are strictly sequential. Each builds on the previous. The additive design means v1 remains the default until P7, so there is zero regression risk during P1-P6.

---

## 3-Package Benchmark Setup

### The Packages

Issue #51 defines a "Tier 2b: Fast Iteration Benchmark" with 3 packages chosen to surface distinct failure classes:

| Package | Per-Iter Time | Current Level | Failure Class | What It Tests |
|---------|--------------|---------------|---------------|---------------|
| `com.jayway.jsonpath:json-path:2.9.0` | ~2.2 min | L2 | `wrong_build_system` (Gradle misidentified as Maven) | Build system detection, template selection. Pre-pass must detect `build.gradle` and route to Gradle template. |
| `junit:junit:4.13.2` | ~2.6 min | L3 | `plugin/configuration_error` + multi-level progression | The ONLY benchmark package hitting 3 levels across attempts. Tests full feedback loop — diagnose plugin errors, recover from L1, push past L3. |
| `commons-fileupload:commons-fileupload:1.5` | ~3.0 min | L3 | L3 stagnation (L3 on attempt 1, stuck 14 iterations) | L3→L4 convergence. Tests stagnation detection, dead-end tracking, L4-specific feedback. |

### packages_fast_iteration.txt

This file does NOT currently exist in the repository. It must be created at `results/packages_fast_iteration.txt` with contents:
```
com.jayway.jsonpath:json-path:2.9.0
junit:junit:4.13.2
commons-fileupload:commons-fileupload:1.5
```

### Running the Benchmark
```bash
buildroot agent --batch results/packages_fast_iteration.txt --pipeline v3 \
  --host rh-h100-01 --max-iterations 5 --output results/fast-iteration-v3/
```

Runtime: ~15 minutes. Capped at 5 iterations per package.

### Per-Package Success Criteria (from issue #51)
- **json-path:** Agent detects Gradle and uses `gradle_base` template (L2+ on first iteration, no `wrong_build_system` errors)
- **junit:** Agent progresses to L3 within 3 iterations (not stuck at L1)
- **commons-fileupload:** Agent reaches L3 AND does not repeat dead-ended approaches

---

## What "Scoring .9" Means

The backlog item says: **"the iteration needs to happen until the 3 packages are at least scoring .9"**

### Reward Formula (Fixed Surface — F3 constraint)
```
reward = 0.05 * L1 + 0.10 * L2 + 0.35 * L3 + l4_score * 0.50
```

### What reward >= 0.9 requires

| Level Reached | Reward Calculation | Result |
|---------------|-------------------|--------|
| L1 only | 0.05 | 0.05 — far from 0.9 |
| L2 only | 0.05 + 0.10 = 0.15 | 0.15 — far from 0.9 |
| L3 only | 0.05 + 0.10 + 0.35 = 0.50 | 0.50 — not enough |
| L4 with l4_score=0.0 | 0.50 + 0.00 = 0.50 | 0.50 — L4 reached but JAR doesn't match |
| L4 with l4_score=0.80 | 0.50 + 0.40 = 0.90 | **0.90 — meets threshold** |
| L4 with l4_score=0.90 | 0.50 + 0.45 = 0.95 | 0.95 — exceeds threshold |
| L4 with l4_score=1.00 | 0.50 + 0.50 = 1.00 | 1.00 — perfect match |

**Achieving reward >= 0.9 requires reaching L4 (JAR produced) with l4_score >= 0.80.** This means the rebuilt JAR must be a close match to the original — at least 80% similarity across the bytecode/structural/metadata comparison dimensions.

For context:
- The 9 currently-solved packages all score >= 0.98 (near-perfect match)
- The 3 benchmark packages currently score 0.15 (json-path, L2), 0.50 (junit, L3), and 0.50 (commons-fileupload, L3)
- Getting all 3 to reward >= 0.9 means solving them to near-L4 quality — a significant improvement from their current state

### This is a High Bar

None of the 3 packages is currently close to 0.9:
- **json-path** (L2, reward=0.15): Needs build system detection fix, then L3, then L4 convergence
- **junit** (L3, reward=0.50): Needs L4 convergence — JAR must match original
- **commons-fileupload** (L3, reward=0.50): Stuck at L3 for 14 iterations in v1 — needs the new feedback loop improvements to break through

The backlog says "iteration needs to happen until... scoring .9" — this implies the factory should keep iterating on the v3 pipeline implementation (adding phases, testing, fixing) until the benchmark proves all 3 packages achieve this level.

---

## Prior Experiment Lessons That Inform Implementation

### Exp #10: THE Critical Anti-Pattern (REVERT, -19.4pp)
**Lesson:** Raw unstructured information dumps to agents cause catastrophic regression. This is encoded as Hard Constraint F1 in issue #51: ALL feedback MUST be structured summaries + file paths, never raw dumps.
**Impact on implementation:** Every `build_feedback_context()` output must follow the structured template format with summaries and explicit Read-tool file paths.

### Exp #10: Early Termination Is Dangerous
**Lesson:** The 3-iteration early termination threshold caused packages that normally solve in 8-12 iterations to get terminated prematurely. Level-only tracking (not reward) missed fine-grained progress.
**Impact:** Stagnation detection uses both value hashes AND rewards. Default max_iterations is 10 (down from 15 but not aggressively low).

### Exp #12: Elitist Gate Works
**Lesson:** The elitist gate with patience counter prevents regression — exploration allowance of 1 iteration is critical. Score delta: +0.025.
**Impact:** Phase 3 implements the elitist gate: on regression, revert to best values and tell the agent.

### Exp #13: Structured Improvements Work
**Lesson:** 8 targeted pipeline critique fixes produced the largest pipeline-quality gain (+0.290).
**Impact:** Targeted, well-scoped improvements to the pipeline beat broad rewrites.

### Exp #15: Complete Values Beat Overrides
**Lesson:** Builder removal and switch to complete template values per iteration (vs spec_overrides) is the right pattern. Eliminates the accumulation bug (A3).
**Impact:** Hard constraint F2 — agent outputs COMPLETE template values every iteration.

### Exp #16: Diagnostic Feedback Must Be Wired
**Lesson:** `build_remediation_context()` existed but had zero call sites. Wiring it produced no score change but enables runtime feedback flow.
**Impact:** Phase 3 replaces this entirely with `build_feedback_context()` which is richer and integrated from the start.

### Memory: E2E Is Mandatory
**Two separate feedback memories** emphasize that after ANY agent/pipeline code change, real E2E on at least 1 package MUST happen. Mocked tests are necessary but not sufficient. Token cost is never a valid skip reason. rh-h100-01 nodes are always available (SSH as `lab`).

### Memory: Discuss Design Changes First
**Feedback memory:** Never change pipeline architecture without discussing with Akash. The factory silently changed build-first to agents-first flow in a prior experiment.

---

## Current Codebase State

### pipeline_v2.py (569 lines)
The starting point for v3. Already implements:
- Observer + Claude Code Analysis Agent flow
- Shallow repo clone
- JAR download
- Structured schema output (BUILDROOT_SCHEMA)
- Complete template values per iteration (not spec_overrides)
- Template rendering via ContainerfileGenerator
- Build evaluation on remote host
- Recipe store caching
- Feedback loop (basic — to be enhanced in P3)

Missing (the 13 gaps from v2 → v3):
1. PrePassFindings structured data model (P1)
2. attempted_but_failed tracking (P1)
3. Confidence + source per field (P1)
4. Elitist gate (P3)
5. Dead-end tracking (P3)
6. Rendered Containerfile in feedback (P3)
7. Cross-package knowledge transfer (P6)
8. Template-value diffs (P3)
9. Warm-start reverse-parse (P6)
10. Parallel first build + analysis (P6)
11. Multiple variants per iteration (P6)
12. Double confirmation build (P3)
13. Score/reward history in structured feedback (P3)

### Test Infrastructure
- 498 existing unit tests (< 1 second runtime, all mocked)
- Evaluator tests, observer tests, pipeline tests exist
- No packages_fast_iteration.txt file yet (must be created)
- packages_benchmark.txt exists (31 packages)
- packages_smoke.txt exists

### Build Infrastructure
- rh-h100-01 available for E2E (SSH as `lab`, not `akasriva`)
- Podman for container builds
- Python 3.14 + claude CLI prereqs on remote nodes

---

## Implementation Strategy Notes

### What the Backlog Asks For
The backlog item says: "solve issue 51, please make sure that the strategist does not drop anything from the scope of the issue. testing needs to be done using the 3 package benchmark and the iteration needs to happen until the 3 packages are at least scoring .9"

This means:
1. **All 8 phases must be addressed** — nothing dropped from issue #51's scope
2. **Testing uses the 3-package fast iteration benchmark** (json-path, junit, commons-fileupload)
3. **Iterate until all 3 packages score reward >= 0.9** — this requires L4 with l4_score >= 0.80

### Practical Implications
- Phases 1-5 are the core implementation (data models, agent enhancement, feedback loop, scoring, CLI)
- Phase 6 optimizations (parallel builds, cross-package transfer, warm-start, multi-variant) may be needed to achieve the .9 threshold on all 3 packages
- Phase 7 (full benchmark) and Phase 8 (cleanup) are post-goal — the 3-package benchmark is the primary validation during development
- The `packages_fast_iteration.txt` file must be created before any benchmark run

### Risk Assessment
- **json-path (L2→0.9):** Requires fixing build system detection (Gradle vs Maven) — this is a pre-pass issue, addressed in P1
- **junit (L3→0.9):** Requires the feedback loop improvements from P3 to push past L3
- **commons-fileupload (L3→0.9):** This is the hardest — stuck at L3 for 14 iterations in v1. Dead-end tracking (P3), better L4 feedback (P3), and possibly multi-signal scoring (P4) are all needed
- All 3 packages reaching 0.9 is ambitious — it means solving 3 currently-unsolved packages to near-L4 quality
