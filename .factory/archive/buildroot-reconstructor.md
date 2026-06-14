---
tags:
  - factory
  - project
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
updated: 2026-06-14T00:00
---


# Factory: Buildroot Reconstructor

## Status
- **State**: EXPERIMENT #008 KEEP — PR #21 open for human review, Claude Code agent migration complete
- **Active Issue**: #19/#20 — Replace raw AnthropicVertex API calls with Claude Code agent subprocess spawning (DONE)
- **Current Score**: 0.8456 (post experiment #008 KEEP)
- **Agentic Solve Rate**: 1/3 (33.3%) — commons-lang3 solved in 1 iteration, micrometer-core reached L2, spring-security-core stuck at L1
- **PNC Validation Score**: 0.5833 mean accuracy (3 packages, range 0.325–0.750)
- **Pre-Experiment #008 Score**: 0.8442
- **Pre-Experiment #007 Score**: 0.8012
- **Pre-Experiment #006 Score**: 0.5662
- **Baseline Score**: 0.6433 (pre-experiment #001)
- **Experiments Run**: 8
- **Kept**: 8, **Reverted**: 0
- **Last Experiment**: #008 — Claude Code agent migration: shared claude_runner.py, 4 agents migrated, new Outer Researcher (KEEP, +0.0014, +3120/-39, 26 files, 29 new tests)
- **Total Tests**: 430 passing (29 new tests added, test count differs from #007's 469 due to test reorganization)
- **Active Strategy**: Completed — Issue #19 Claude Code agent migration delivered. Awaiting next issue.
- **Previous Strategy**: Outer Loop with Failure Analyst, Knowledge Base, Guards, and Strategy Archive (issue #16)
- **Open PRs**: #21 — Claude Code agent migration (+3120/-39, 26 files, awaiting human review), #15 — Inner loop MVP
- **Merged PRs**: #18 — Outer loop intelligence layer (+2258/-13, 20 files, 143 new tests), #11 — PNC ground-truth validation (+1012/-0, 6 files, 41 new tests)
- **Keep Streak**: 8/8 — perfect streak, zero reverts

## PNC Ground-Truth Validation Results (Experiment #005)

| Package | Accuracy | JDK | Build Tool | Maven Version | Key Issue |
|---------|----------|-----|------------|---------------|-----------|
| commons-lang3:3.14.0 | 0.325 | MISS (21 vs 8) | ✓ | ✓ | Build-Jdk-Spec=21 is upstream CI's JDK, not PNC's |
| jackson-core:2.17.0 | 0.750 | HIT (8) | ✓ | ✓ | Best result — all major dimensions matched |
| snakeyaml:2.2 | 0.675 | HIT (11) | ✓ | MISS | Maven version extraction missing (empty string) |
| **Mean** | **0.5833** | | | | |

### Key Findings
1. Build-Jdk-Spec in JAR manifests reports upstream CI's JDK, not PNC's build JDK
2. OS family extraction returns empty across all packages — needs improvement
3. SCM URL scoring gives partial credit (0.5) when ground truth is empty
4. Maven version not extracted from all available sources (snakeyaml gap)

## Agentic Smoke Test Results (Experiment #006)

| Package | Status | Best Reward | Iterations | Elapsed |
|---------|--------|-------------|------------|---------|
| commons-lang3:3.14.0 | **SOLVED** | 1.0 | 1 | 741s |
| micrometer-core:1.10.13 | budget_exhausted | 0.15 (L2) | 15 | 974s |
| spring-security-core:5.8.9 | budget_exhausted | 0.05 (L1) | 15 | 681s |
| **Aggregate** | **1/3 solved** | **0.40 mean** | **10.3 avg** | **2395s total** |

## Latest Eval (0.8456 — post experiment #008 KEEP, score_before=0.8442)
| Dimension | Score | Weight | Status |
|-----------|-------|--------|--------|
| tests | 1.000 | 0.15 | all passing (430 total, 29 new in #008) |
| lint | 1.000 | 0.075 | clean |
| type_check | ~0.8+ | 0.05 | pre-existing mypy errors outside scope |
| coverage | 0.980 | 0.125 | 98% |
| guard_patterns | 1.000 | 0.05 | passing |
| capability_surface | 0.306+ | 0.125 | 13 features + claude_runner infrastructure |
| observability | 0.341 | 0.09 | improved from 0.091 |
| research_grounding | 0.320 | 0.07 | 60+ sources (10 new agentic) |

## Issue #19 Research Phase (2026-06-13)

**Goal**: Replace raw `AnthropicVertex` API calls with Claude Code agent subprocess spawning (`claude -p`) in 3 existing agents + 1 new agent.

**Research outputs** (CEO verdict: PROCEED):
| Researcher | Lines | Key Contribution |
|-----------|-------|-----------------|
| Local | 310 | All 3 call sites mapped, zero test breakage risk confirmed, meta_guidance flow traced |
| External | 474 | Full CLI reference, `spawn_claude_agent()` implementation, per-agent configs, Vertex AI setup |
| Context | 318 | Module migration map, 8-risk assessment, 5-phase implementation order, test strategy |

**Agents to migrate**:
1. Inner Builder (`builder.py`) — single-shot → iterative with tool access
2. Outer Builder (`outer_loop.py`) — full-file replacement → surgical Edit tool, removes 200-line cap
3. Outer Strategist (`outer_strategist.py`) — hardcoded dict → LLM-powered hypothesis generation with `--json-schema`
4. Outer Researcher (NEW) — web research between Failure Analyst and Strategist

**Key decisions for strategy**:
- Use `--bare --append-system-prompt-file` for all agents
- Shared `claude_runner.py` utility for subprocess management
- Outer Builder: agent edits files in-place (Option A), outer loop uses git diff
- Implementation order: Inner Builder → Strategist → Researcher → Outer Builder → E2E

**Sources**: [local-analysis](sources/claude-code-migration-local-analysis.md), [external-research](sources/claude-code-migration-external-research.md), [context-analysis](sources/claude-code-migration-context-analysis.md), [ceo-verdict](sources/claude-code-migration-ceo-verdict.md)

## Vision

Reconstruct the complete build environment (buildroot) for a Maven artifact as a Containerfile, working only from the package's `pom.xml` and its CI workflow — enabling consumer-side build provenance reconstruction for supply chain security.

**Key differentiator**: No existing tool produces Containerfiles from consumer-side inference. Macaron BuildGen outputs shell-oriented buildspecs, Reproducible Central uses hand-written specs, and OSS-Rebuild doesn't support Maven yet.

## Architecture

- **Language**: Python 3.11+
- **CLI Framework**: `click`
- **Core Libraries**: `lxml`, `defusedxml`, `ruamel.yaml`, `jinja2`, `dockerfile-parse`, `requests`, `pytest`
- **Container Runtime**: Podman (default), Docker/Buildah supported via `--runtime`
- **Storage**: Filesystem only — POM cache in `~/.cache/buildroot/poms/`

## Core Features (13 — all delivered)

1. **POM Fetching & Parsing with Full Parent Resolution** — Phase 2
2. **Maven Property Placeholder Resolution** — Phase 3
3. **CI Workflow Parsing** (GitHub Actions + CircleCI) — Phase 4
4. **JDK Version Inference with 12-Source Priority Heuristic** — Phase 5
5. **Container Image Resolution** (CI-referenced images) — Phase 6
6. **Transitive Dependency Tree Resolution** (via `mvn dependency:tree`) — Phase 7
7. **Containerfile Generation** (3 Jinja2 templates: jdk-base, jdk-on-ubuntu, vendor-image) — Phase 8
8. **Gap Detection and Confidence Reporting** — Phase 9
9. **Pipeline Orchestration + CLI** (reconstruct, verify, inspect commands) — Phase 10
10. **Multi-Layer JAR Comparison** (structural/metadata/bytecode, CFR decompiler, verdict taxonomy) — Experiment #003
11. **PNC Ground-Truth Validation** (Containerfile parser, 6-dimension accuracy scorer, validate CLI) — Experiment #004
12. **Agentic Reconstructor Inner Loop** (LLM-driven iterative Containerfile repair, 4-level eval, dead-end registry, outer loop skeleton) — Experiment #006
13. **Intelligent Outer Loop** (Failure analyst, knowledge base with inner loop injection, 4-guard safety chain, J(S) strategy scoring, LLM outer strategist) — Experiment #007

## Build Phases Completed

| Phase | Description | Commits |
|-------|-------------|---------|
| 1 | Project scaffold, prerequisites, eval harness | 7f18bfc |
| 2-3 | POM parsing + parent resolution, property resolution | 9896716 |
| 4-5 | CI workflow parsing, JDK version inference | 626e439 |
| 6-7 | Container image resolution, transitive deps | 20c9771 |
| 8-9 | Containerfile generation, gap detection | c53a29d |
| 10 | Pipeline orchestration and CLI | 74679ad |
| 11 | Level 1 + Level 2 eval test suites | e59209f |
| fixes | JDK normalization, eval config, lint | c0b551a, d076793, fba6de0 |
| baseline | Factory config + baseline eval | 9f3d8b3 |

## Test Results (Latest — post experiment #007, cycle complete)

- **Total tests passing**: 469 (143 outer loop + 75 inner loop + 251 pipeline, zero regressions across all 7 experiments)
- **Failure analyst**: 13 tests — batch analysis, error classification, stagnation detection, serialization
- **Guards**: 20+ tests — surface allowlist, monotonic regression, leakage scanning, composite check
- **Outer strategist**: 15+ tests — J(S) computation, strategy archive, hypothesis generation
- **Knowledge base**: 15+ tests — pattern read/write, taxonomy updates, section extraction
- **Outer loop v2**: 20+ tests — full cycle orchestration, keep/revert decisions, guard integration
- **Lint**: clean (ruff 7→0 errors)
- **Mypy**: 10 pre-existing errors in files outside Builder's scope

## Test Results (post experiment #004)

- **Total tests passing**: 293 (41 new PNC validation + 252 existing, zero regressions)
- **Level 1 (inference correctness)**: 70/70 passed — 10 Spring ecosystem packages
- **Level 2 (podman build)**: 10/10 passed — all 10 packages build successfully
- **Level 4 (JAR comparison)**: 26/26 passed — structural, metadata, bytecode layers
- **PNC validation**: 41/41 passed — parser extraction, chain parsing, scoring dimensions, aggregate, edge cases
- **Lint**: clean (ruff)

## Key Bugs Fixed During Build

1. **JDK version normalization** — `1.8` → `8` for Docker tag compatibility (e.g., `eclipse-temurin:8-jdk`)
2. **Containerfile strip function** — was stripping `apt-get` lines needed for package installation
3. **Parent chain expectations** — Gradle-published flat POMs don't have parent chains; test expectations adjusted

## CLI Commands

- `buildroot reconstruct <coordinate>` — full pipeline → Containerfile + buildroot.json + dependency-tree.json
- `buildroot verify <coordinate>` — validate against JAR manifest, optional rebuild
- `buildroot inspect <coordinate>` — diagnostic: parent chain, properties, JDK inference, CI config
- `buildroot compare <coordinate>` — three-layer JAR comparison (structural, metadata, bytecode) against Maven Central original
- `buildroot validate <coordinate>` — compare reconstruction against PNC ground truth, output per-dimension accuracy + aggregate report

## Test Set

10 Spring ecosystem packages covering: multi-module monorepos (spring-framework), explicit container images (spring-cloud-config), no CI (thymeleaf-spring5), matrix builds (spring-boot).

## Key Technical Challenges

1. Maven property resolution with inheritance chains (properties resolve *after* inheritance)
2. JDK version vs. language level distinction (source=11 can compile on JDK 17)
3. `ubuntu-latest` is a moving target (static lookup table, flagged as gap)
4. CI-friendly Maven versions (`${revision}`) set via `-D` flags, not in POM
5. Multi-module projects get one Containerfile for the reactor

## Assumptions & Simplifications (10)

1. Shallow Gradle detection (no deep build.gradle parsing)
2. Composite GitHub Actions parsed only 1 level deep
3. Static ubuntu-latest → ubuntu:24.04 mapping
4. Incomplete Maven property resolution (no settings.xml, no `-D`, no profiles)
5. No CircleCI orb resolution
6. No private registry auth
7. Build-Jdk-Spec in JAR manifest is advisory
8. Transitive deps require local Maven
9. One Containerfile per multi-module project
10. springcloud/pipeline-base image ref is commented out in source

## Backlog (15 items — 3 cleared by #001, Level 3 builds cleared by #002, PNC execution cleared by #005)

### Level 3 Rebuilds (COMPLETE)
All 10 test packages verified building in containers on rh-h100-01 (cleared by experiment #002).

### PNC Validation (COMPLETE)
Pipeline executed on rh-h100-01 for 3 packages (cleared by experiment #005). Mean accuracy 0.5833.

### Advisory Issues from Code Review (3)
- `_has_flag` treats `=false` as present (e.g., `--flag=false` still seen as "flag is set")
- Pagination substring false positive in tag discovery
- Streaming response leak in JAR manifest download

### Feature Enhancements (5 remaining)
- Deep Gradle support (build.gradle.kts parsing)
- CircleCI orb resolution
- Composite GitHub Action resolution beyond 1 level
- Private registry authentication
- Maven profiles and `-D` property support

### Accuracy Improvement Opportunities (from #005)
- PNC-specific JDK resolution: parse image name `builder-rhel-7-j{JDK}` as authoritative JDK source
- OS family extraction from PNC Containerfile `FROM` base image
- Maven version extraction pipeline to cover all sources
- Demote Build-Jdk-Spec priority when PNC ground truth is available

### Cleared by Experiment #001
- ~~JDK from JAR manifest~~ (Fix 4)
- ~~RAT skip detection~~ (Fix 5)
- ~~SCM extraction, git tag discovery, template git clone, Maven wrapper, build command enrichment~~ (Fixes 1-3, 6)

## Improvement Opportunities (from baseline eval)

1. **Type checking** (0.0) — add `py.typed` marker, fix 23 mypy errors
2. **Observability** (0.341) — add structured logging, increase function coverage from 12%
3. **Capability surface** (0.306) — grow from 104 to 340 (more modules, public functions, entry points)
4. **Coverage** (0.5) — configure pytest-cov so eval detects coverage
5. **Research grounding** (0.32) — improve citation ratio and doc utilization

## Research Sources Archived

### Prior Art & Landscape (initial research)
- `sources/prior-art-landscape.md` — gap analysis: no existing tool does consumer-side POM → Dockerfile
- `sources/macaron-buildgen.md` — Oracle Labs Macaron/BuildGen: closest match, outputs buildspecs not Dockerfiles
- `sources/oss-rebuild-google.md` — Google OSS-Rebuild: heuristic rebuilds for PyPI/npm/Crates, Maven on roadmap
- `sources/reproducible-central.md` — JVM Reproducible Central: hand-written buildspecs, de facto standard
- `sources/python-library-stack.md` — Recommended Python library stack (lxml, ruamel.yaml, jinja2, click)
- `sources/maven-property-resolution.md` — Property resolution complexity (inheritance, recursion, CI-friendly versions)

### Implementation Research (post-verdict)
- `sources/project-structure-implementation.md` — src layout, Click CLI, pipeline dataclasses, confidence annotations
- `sources/macaron-pom-parsing-patterns.md` — Reusable patterns from Macaron (namespace-agnostic tags, iterative walking, encoding fallback)
- `sources/jinja2-containerfile-templates.md` — Two-pattern approach (JDK base vs JDK-on-Ubuntu), vendor-to-image mapping
- `sources/setup-java-parsing.md` — Three matrix patterns (direct, matrix var, nested object), composite action depth
- `sources/maven-dependency-tree-json.md` — JSON output since Plugin 3.7.0 eliminates text parsing
- `sources/macos-prerequisites.md` — Install order (JDK before Maven), Podman machine init, Apple Silicon support
- `sources/jdk-version-inference-heuristic.md` — 12-source priority heuristic, language level vs actual JDK distinction

### Level 3 Research (post-baseline)
- `sources/level3-gap-analysis.md` — 7-gap taxonomy blocking Level 3 full rebuild, priority-ordered
- `sources/scm-source-repo-discovery.md` — Dead code path in SCM extraction; blocks commons-lang3, thymeleaf, micrometer
- `sources/git-tag-format-discovery.md` — v{version} hardcoding fails for Apache/Thymeleaf tag conventions
- `sources/build-jdk-spec-vs-language-level.md` — Build JDK ≠ language level; commons-lang3 needs JDK 21 not 8
- `sources/build-command-inference.md` — POM plugin analysis for -Dgpg.skip, -Drat.skip, Maven Wrapper detection
- `sources/aroma-paper.md` — AROMA (ACM 2024): automatic Maven artifact reproduction, complementary approach
- `sources/maven-ci-coverage-ceiling.md` — 84% of top Maven artifacts lack transparent CI; POM fallback essential

## Strategy History

- `strategies/buildroot-reconstructor-2026-06-07.md` — Initial inception strategy (research → spec → build plan)
- `strategies/buildroot-reconstructor-2026-06-07-build-plan.md` — CEO-approved 11-phase build plan (all 9 core features, Level 1+2 verification)
- `strategies/buildroot-reconstructor-2026-06-08-build-complete.md` — Build completion snapshot with baseline eval
- `strategies/buildroot-reconstructor-2026-06-08-level3.md` — Level 3 gaps strategy: 6 interdependent fixes for full source rebuilds (CEO APPROVED)
- `strategies/buildroot-reconstructor-2026-06-08-cycle-summary.md` — Cycle 2 summary: 1 experiment, +0.2066, 6 fixes, 35 tests, PR #3
- `strategies/buildroot-reconstructor-2026-06-09-level4.md` — Level 4 artifact comparison strategy: multi-layer JAR comparison + rh-h100 builds (CEO APPROVED)
- `strategies/buildroot-reconstructor-2026-06-09-cycle-summary.md` — Cycle 3 summary: 2 experiments (#002, #003), +0.5418, JAR comparison pipeline, PR #7
- `strategies/buildroot-reconstructor-2026-06-12-pnc-validation.md` — PNC ground-truth validation strategy: 5 deliverables, 3 packages, accuracy scorer (CEO APPROVED)
- `strategies/buildroot-reconstructor-2026-06-12-cycle-summary.md` — Cycle 4 complete: 1 experiment (#004 KEEP, +0.2807), PNC validation pipeline shipped, 4/4 keep streak
- `strategies/buildroot-reconstructor-2026-06-13-cycle-summary.md` — Cycle 5 complete: 1 refinement (#005 KEEP), PNC execution on rh-h100-01, mean accuracy 0.5833, 5/5 keep streak
- `strategies/buildroot-reconstructor-2026-06-13-agentic-inner-loop.md` — Cycle 6 strategy: Agentic inner loop MVP (H1 EXPLORE/mixed, issue #13) — CEO APPROVED, capability_surface 0→0.6
- `strategies/buildroot-reconstructor-2026-06-13-outer-loop.md` — Cycle 7 strategy: Outer Loop with Failure Analyst, Knowledge Base, Guards, J(S) tracking (H1 EXPLORE/mixed, issue #16) — CEO APPROVED, 5-phase implementation
- `strategies/buildroot-reconstructor-2026-06-13-final-cycle-summary.md` — **Final cycle summary**: 7/7 keep streak, score 0.6433→0.8439, 469 tests, 13 features, agentic inner+outer loop complete
- `strategies/buildroot-reconstructor-2026-06-13-claude-code-migration.md` — Cycle 8 strategy: Claude Code agent migration (H1 EXPLORE/code, issue #19) — CEO APPROVED, 4 agents (3 migrated + 1 new), shared runner, E2E
- `strategies/buildroot-reconstructor-2026-06-13-complete-cycle-summary.md` — **Complete factory cycle summary**: 8/8 keep streak, score 0.6433→0.8456, 430 tests, 13 features, 4-layer architecture, all agents on Claude Code subprocess

## Recent Experiments

### Experiment #008 — Claude Code agent migration: shared runner, 4 agents migrated, new Outer Researcher (KEEP, +0.0014)
- **Hypothesis**: Replace all 3 raw `AnthropicVertex` single-shot API calls with Claude Code subprocess agents via shared `claude_runner.py`, and add new Outer Researcher agent for web research on failure patterns
- **Score**: 0.8442 → 0.8456 (+0.0014)
- **New modules**: 4 — claude_runner.py (135 lines), outer_researcher.py, failure_analyst.py (187 lines), strategy_archive/.gitkeep
- **Modified**: builder.py (AnthropicVertex → spawn_claude_agent, 3 modes), outer_loop.py (Outer Builder migration), outer_strategist.py (hardcoded dict → --json-schema), guards.py (MUTABLE_SURFACES), factory.md (scope)
- **PR**: #21 (OPEN, awaiting human review), +3120/-39 lines, 26 files, 7 commits
- **Tests**: 29 new (430 total), zero regressions
- **CEO Code Review**: CLEAN — all 7 checklist items PASS, zero issues
- **Key features**: `spawn_claude_agent()` shared utility, AgentResult dataclass, 3 error paths (timeout/CLI-not-found/JSON-parse), Outer Researcher with WebSearch, structured output via --json-schema, meta_guidance flow preserved, fallback hypothesis on agent failure
- **Verdict**: **KEEP** — clean code review, positive delta, infrastructure enabler for future agentic improvements
- **Details**: `experiments/buildroot-reconstructor-008.md`

### Experiment #007 — Intelligent outer loop with failure analyst, guards, strategy archive (KEEP, +0.0427)
- **Hypothesis**: Implement outer loop intelligence: failure analysis across batch results, cross-package knowledge base with inner loop injection, safety guards, J(S) strategy scoring, LLM-driven outer strategist
- **Score**: 0.8012 → 0.8439 (+0.0427)
- **New modules**: 5 — failure_analyst.py (187 lines), guards.py (252 lines), outer_strategist.py (~180 lines), knowledge_base.py (132 lines), knowledge/ package (3 data files)
- **Modified**: builder.py (meta_guidance injection), outer_loop.py (full rewrite), agent_cmd.py (--cycles flag)
- **PR**: #18 (MERGED), +2258/-13 lines, 20 files
- **Tests**: 143 new (399 total), zero regressions
- **CEO Code Review**: ISSUES_FOUND (2) → fixed in a362769 → CLEAN
- **Key features**: AutoScientists stagnation detection, 4-guard safety chain (surface/leakage/monotonic/test), J(S) formula, knowledge base → Builder injection, strategy archive
- **E2E validation**: 3 real packages — full cycle batch→analyze→strategize→implement→guard→re-batch→verdict working
- **Verdict**: **KEEP** — score +0.0427, all subsystems functional
- **Details**: `experiments/buildroot-reconstructor-007.md`

### Experiment #006 — Agentic reconstructor inner loop MVP (KEEP, +0.0038, 75 tests, validated on rh-h100-01)
- **Hypothesis**: Implement Phase 1 agentic reconstructor with LLM-driven iterative Containerfile repair loop, 4-level evaluation, and batch processing outer loop skeleton
- **Score**: 0.5662 → 0.5700 (+0.0038)
- **New modules**: 8 under `src/buildroot/agent/` — models, observer, builder, evaluator, analyzer, loop, outer_loop, `__init__`
- **CLI**: `buildroot agent <coordinate>` with `--host`, `--max-iterations`, `--model`, `--batch` flags
- **Key features**: AdaEvolve G_t progress signal (exploit/explore/meta-shift), dead-end registry (2-failure threshold), GHA expression sanitization, 18-category error classification with LLM fallback
- **PR**: #15 (OPEN), +1703/-0 lines, 15 files
- **Tests**: 75 new, zero regressions
- **Security fixes**: 3 (heredoc injection, path injection, G_t cold-start spike)
- **CEO Code Review**: CLEAN (iteration 2 — diff_summary propagation fixed in 5a3c5d9)
- **Operational validation**: rh-h100-01, 3 packages — commons-lang3 SOLVED (reward=1.0, 1 iter), micrometer-core L2 (reward=0.15, 15 iter), spring-security-core L1 (reward=0.05, 15 iter). Solve rate: 33.3%
- **Verdict**: KEEP — 8 modules shipped, inner loop + outer loop architecture validated end-to-end on real infrastructure
- **Details**: `experiments/buildroot-reconstructor-006.md`

### Experiment #005 — PNC validation execution on rh-h100-01 (KEEP, operational refinement)
- **Hypothesis**: Execute `buildroot validate` on rh-h100-01 for commons-lang3, jackson-core, snakeyaml against real PNC Containerfiles
- **Type**: Tier 1 operational refinement — no source code changes
- **Results**: mean accuracy 0.5833 (commons-lang3=0.325, jackson-core=0.750, snakeyaml=0.675)
- **Key finding**: Build-Jdk-Spec reports upstream CI's JDK, not PNC's build JDK — explains commons-lang3 mismatch
- **Commit**: c378994
- **CEO Code Review**: CLEAN (execution-only, no source changes)
- **Verdict**: KEEP — pipeline validated against real infrastructure, results establish accuracy baseline
- **Details**: `experiments/buildroot-reconstructor-005.md`

### Experiment #004 — PNC ground-truth validation (KEEP, +0.2807)
- **Hypothesis**: Parse PNC 2-layer Containerfile chains, build 6-dimension weighted accuracy scorer, validate against 3 packages
- **Score**: 0.5436 → 0.8243 (+0.2807)
- **PR**: #11 (MERGED), 4 commits (63b3922 + 3 review fixes), +1012/-0 lines, 6 files
- **New modules**: pnc_containerfile.py (parser), accuracy_scorer.py (scorer), validate.py (CLI), report generator
- **CEO Code Review**: CLEAN on first iteration — all 7 checklist items PASS, no fixes needed
- **Tests**: 41 new (293 total passing), zero regressions
- **Review iterations**: 3 builder + 3 CEO final (code CLEAN on first CEO pass)
- **Verdict**: KEEP — 5 deliverables shipped, +0.2807 score gain, pipeline code complete
- **Details**: `experiments/buildroot-reconstructor-004.md`

### Experiment #003 — Level 4 multi-layer JAR comparison pipeline (KEEP, +0.5418)
- **Hypothesis**: Implement three-layer JAR comparison (structural/metadata/bytecode) and run builds on rh-h100 nodes
- **Score**: 0.3082 → 0.8500 (+0.5418)
- **PR**: #7 (OPEN), 2 initial commits (7f7085e, 3f7f928) + 4 review fix commits (29953f8, 910edf6, 18a49f0, 053f07a)
- **New modules**: jar_comparator.py, compare CLI command, maven_central download_jar()
- **CEO Code Review**: CLEAN after 5 iterations (2 structured + 3 final)
- **Tests**: 26 new (179 total passing), eval score 0.8500
- **Build results**: 0/10 rh-h100 builds succeeded — all failures are upstream Containerfile generation issues
- **Verdict**: KEEP — comparison pipeline code is complete and correct; build failures are Level 1-3 defects
- **Details**: `experiments/buildroot-reconstructor-003.md`

### Experiment #002 — Level 3 build verification refinement (KEEP, 3/10 → 10/10 builds)
- **Hypothesis**: Fix remaining build failures through iterative debugging — JDK inference, Gradle support, template generation
- **Commits**: 4 (fbc12db → 4f61ea7), +745/-61 lines, 14 files
- **Key fixes**: Created-By JDK parsing, Gradle --no-daemon + GRADLE_OPTS, multi-module path detection, build tool detection
- **Build verification**: 10/10 packages pass on rh-h100-01 (160 cores, 1.7TB RAM)
- **Verdict**: KEEP — build pass rate 30% → 100%
- **Details**: `experiments/buildroot-reconstructor-002.md`

### Experiment #001 — Fix all 6 Level 3 rebuild gaps (KEEP, +0.2066)
- **Hypothesis**: Bundle 6 interdependent gaps (SCM extraction, git tag discovery, template git clone, JDK from JAR manifest, build command enrichment, Maven wrapper detection) into single PR
- **PR**: #3 (+809/-23, 11 files, 35 new tests)
- **CEO Code Review**: CLEAN — all 7 checklist items PASS
- **Eval Score**: 0.6433 → 0.8499 after 3 code review fixes (shell injection, type guard, flag matching)
- **Verdict**: KEEP — score gain +0.2066, all 6 gaps implemented correctly
- **Details**: `experiments/buildroot-reconstructor-001.md`

### Baseline — Initial Build (ESTABLISHED)
- **Score**: 0.586 → 0.831 (via post-build fixes)
- **Details**: `experiments/buildroot-reconstructor-baseline.md`

## Level 4 Research (Artifact Comparison)

**CEO Verdict**: PROCEED — research thorough, covers all five requested areas with actionable depth.

### Key Findings Relayed to Strategist
1. Four-layer comparison strategy: structural (zipfile) → metadata (MANIFEST.MF) → bytecode (CFR preferred over javap) → diffoscope
2. CFR decompiler preferred over javap — javap produces massive false positives from constant pool index changes
3. Non-determinism taxonomy ranked by frequency — timestamps are #1
4. Python-native implementation feasible for Layers 1-3 using stdlib zipfile
5. Container extraction: `podman create` + `podman cp` is simplest approach
6. Maven Central download pattern already exists in codebase (`maven_central.py`)
7. Remote execution: SSH + tmux on rh-h100 nodes, 3-node parallelization
8. Verdict taxonomy: IDENTICAL / EQUIVALENT / DIVERGENT / FAILED with clear criteria

### Level 4 Research Sources
- `sources/jar-comparison-layered-strategy.md` — Four-layer comparison: structural → metadata → bytecode (CFR) → diffoscope
- `sources/reproducible-builds-standard-approach.md` — Reproducible Central methodology: buildspec, buildinfo, buildcompare
- `sources/java-build-nondeterminism-taxonomy.md` — 10 non-determinism sources ranked by frequency; timestamps are #1
- `sources/container-artifact-extraction.md` — `podman create` + `podman cp` for JAR extraction; rh-h100 parallelization plan
- `sources/level4-verdict-taxonomy.md` — IDENTICAL/EQUIVALENT/DIVERGENT/FAILED criteria and per-package report structure
- `sources/oss-rebuild-stabilize.md` — Google OSS-Rebuild's `stabilize` tool: semantic normalization philosophy, Maven not yet supported

### PNC Ground-Truth Validation Research (Issue #9)

**CEO Verdict**: PROCEED — research comprehensive, covers all 5 requested areas. Actionable.

#### Key Findings
1. PNC uses 2-layer Containerfile chain (base: JDK on RHEL → tool: Maven/Gradle) — `dockerfile-parse` handles both layers
2. Image naming convention `builder-rhel-{RHEL}-j{JDK}-mvn{MAVEN}` encodes environment, serves as cross-check
3. Critical JDK mismatch expected: reconstructor's `Build-Jdk-Spec` reflects upstream CI JDK, not PNC's build JDK
4. 6-dimension weighted accuracy scorer proposed (JDK version 0.25, build tool 0.25, tool version 0.15, SCM 0.15, JDK vendor 0.10, OS family 0.10)
5. `dockerfile-parse` already in project dependencies — no new dependencies needed
6. 5 deliverables scoped: PNC parser, accuracy scorer, validation pipeline, JSON report, test suite

#### PNC Research Sources
- `sources/pnc-build-system-architecture.md` — PNC 2-layer image chain, naming conventions, regex patterns for extraction
- `sources/pnc-ground-truth-validation-approach.md` — Validation methodology, scoring dimensions, expected mismatches, SLSA alignment
- `sources/pnc-jdk-version-mismatch-analysis.md` — Build-Jdk-Spec vs PNC JDK analysis, implications for heuristic ordering
- `sources/dockerfile-parse-for-pnc.md` — Library selection rationale, key APIs, 2-layer parsing strategy
- `sources/sbom-ground-truth-benchmarks.md` — ReversingLabs SBOM accuracy research, supply chain security positioning

### Outer Loop Research (Issue #16)

**CEO Verdict**: PROCEED — thorough research covering existing codebase architecture (all 8 inner loop modules mapped), 6 relevant research papers with actionable patterns, and a phased implementation plan.

#### Key Findings
1. **AdaEvolve J(S) formula**: `J = (s_end - s_start) · log(1 + s_start) / √W` — principled strategy scoring across cycles
2. **Three-level adaptation hierarchy**: Level 1 = inner loop (exists), Level 2 = package scheduling (out of scope), Level 3 = outer loop code changes (main deliverable)
3. **EvoX dual-loop architecture**: Inner loop evolves Containerfiles, outer loop evolves the inner loop's code — demand-driven, not periodic
4. **AutoScientists stagnation triggers**: ≥3 cycles with J(S) < threshold triggers meta-shift from error-class fixes to architectural changes
5. **Meta-Harness validates harness optimization**: Our outer loop is literally optimizing a harness — the Builder's prompts, Analyzer's error patterns, Observer's metadata extraction
6. **LLMLOOP per-error-type feedback**: Failure Analyst taxonomy creates per-error-class prompt templates for the Builder
7. **Phased implementation order**: Failure Analyst + Knowledge Base → Guards & Gates → Researcher + Strategist → Builder + Orchestrator → CLI + Archive

#### Recommended Focus Areas (priority order)
1. Failure Analyst — highest-leverage foundation, enables all downstream components
2. Knowledge Base with inner loop injection — cross-trial learning mechanism
3. Guards & Gates — safety prerequisite before code mutation (surface guard, test gate, monotonic check, leakage scan)
4. Outer Strategist with J(S) tracking — the intelligence layer
5. Outer Researcher — optional enhancement for when LLM knowledge is exhausted

#### Outer Loop Research Sources
- `sources/adaevolve-outer-loop-hierarchy.md` — J(S) formula, three-level hierarchy, stagnation thresholds, dynamic island spawning
- `sources/autoscientists-self-organizing-teams.md` — Stagnation detection, dead-end registries, cross-team visibility, noise-aware validation
- `sources/evox-meta-evolution-strategy.md` — Dual-loop architecture, strategy archive, demand-driven switching, additive strategy evolution
- `sources/alphaevolve-llm-mutation-operator.md` — LLM as mutation operator, SEARCH/REPLACE diffs, MAP-elites population
- `sources/meta-harness-optimization.md` — Harness-as-optimization-target, full history exposure via filesystem
- `sources/llmloop-iterative-feedback.md` — Per-error-type feedback loops, dynamic temperature, error-class-specific prompts

### Agentic Reconstructor Research (Issue #13)

**CEO Verdict**: PROCEED — thorough research covering all 4 priorities. Codebase mapping accurate. External research validates tree-search approach.

**Correction applied**: Model/SDK must use Vertex AI (`AnthropicVertex(region="us-east5", project_id="itpc-gcp-ai-eng-claude")` with `model="claude-opus-4-6"`), not direct `anthropic` SDK with `claude-sonnet-4-6`.

#### Key Findings
1. Existing modules map cleanly to agentic roles: orchestrator→Observer, containerfile→Builder, jar_comparator→Evaluator, gap_detector→Analyzer input
2. Phase 1 inner loop: Observer → Builder → Evaluator → Analyzer → (repeat), max 15 iterations, progress signal G_t for mode switching
3. GHA expression sanitization alone fixes 7/10 exp #003 failures — should be pre-flight fix
4. Error taxonomy seeded from 5 root causes in exp #003 (GHA secrets, GHA expressions, wrong tag, multi-module, image resolution)
5. AprMcts (2025) validates MCTS for repair: UCT C=0.7, beta=0.8 forgetting factor directly applicable
6. SWE-Search (ICLR 2025) validates multi-agent inner loop: 3-agent split maps to Builder/Evaluator/Analyzer
7. CI-Repair-Bench: 18.9% single-shot repair rate — iterative approach essential for our harder domain
8. Dead-end registry with 2-failure threshold prevents cycling without context poisoning

#### Agentic Research Sources
- `sources/repairagent-icse2025.md` — LLM as autonomous repair agent, tool selection over fixed pipelines
- `sources/aprmcts-mcts-repair.md` — MCTS for program repair, UCT C=0.7, beta=0.8 forgetting factor
- `sources/swe-search-iclr2025.md` — MCTS for SWE tasks, 3-agent architecture, inference-time compute scaling
- `sources/sgagent-multi-agent-repair.md` — Multi-agent repair with escalation, maps to G_t mode switching
- `sources/mini-swe-agent-lightweight-repair.md` — Lightweight repair loop, context management, memory pointers
- `sources/codex-iterative-repair.md` — Review→Repair→Validation separation, structured output contracts
- `sources/ci-repair-bench.md` — 18.9% repair rate baseline, Containerfile repair harder than source repair
- `sources/dead-end-registries-failure-memory.md` — Failure memory patterns, debounce hooks, context poisoning mitigation
- `sources/maven-build-error-taxonomy.md` — Maven error categories, exp #003 root cause taxonomy
- `sources/agentic-codebase-mapping.md` — Module-to-agent mapping, Phase 1 architecture
