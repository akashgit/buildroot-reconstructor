---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-09
source: factory-archivist
---

# Strategy: Buildroot Reconstructor — 2026-06-09

## Context
Level 3 verified all 10 test packages build from source (10/10, experiment #002 kept). Level 4 is the natural next step — artifact comparison against Maven Central originals. Research phase complete; CEO verdict: PROCEED.

## CEO Verdict
**PROCEED** — Single hypothesis correctly targets the Level 4 backlog item (issue #5). Mixed type with proper Execution step and Expected output fields. Scope stays within declared surfaces. Anti-patterns well-identified. No issues found. PLAN APPROVED.

## Approved Hypothesis

### H1: Level 4 artifact comparison — implement multi-layer JAR comparison pipeline and run builds on rh-h100 nodes
- **Category:** EXPLORE
- **Type:** mixed (code + operational)
- **Backlog item:** Level 4: Artifact comparison — verify rebuilt JARs against Maven Central originals (issue #5)

**Code changes (5 modules):**
1. `src/buildroot/utils/jar_comparator.py` — three-layer comparison: structural (zipfile), metadata (MANIFEST.MF with non-determinism stripping), bytecode (CFR decompiler, javap fallback)
2. `src/buildroot/utils/maven_central.py` — extend with `download_jar()` + SHA-1 verification
3. `src/buildroot/cli/commands/compare.py` — new CLI command `buildroot compare`
4. `src/buildroot/pipeline/orchestrator.py` — extend `verify()` with `--rebuild` flag
5. `tests/test_jar_comparator.py` — unit tests for all three comparison layers

**Verdict taxonomy:** IDENTICAL (byte-for-byte SHA-256 match) | EQUIVALENT (same logic after stripping non-determinism) | DIVERGENT (structural/bytecode differences) | FAILED (build or download failure)

**Execution plan:** SSH into 3 rh-h100 nodes, tmux sessions, podman build + create + cp for JAR extraction, download originals from Maven Central, run comparison pipeline across all 10 packages.

**Expected output:** Per-package JSON comparison reports, overall summary (% IDENTICAL + EQUIVALENT), human-readable summary.md, build logs.

**Expected impact:**
- capability_surface: significant increase
- tests: 0.0 → 0.7+ (fix module import + new tests)
- coverage: 0.0 → 0.5+
- type_check: 0.4 → 0.6+
- observability: 0.1 → 0.2+
- spec_compliance: 0.5 → 0.8+

## Design Space Assessment
| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | Level 1–3 pipelines built and verified (10/10 builds) |
| Bug fixes | 3 | Shell injection, type guards, flag matching fixed |
| Instrumentation | 1 | Only 14/110 functions instrumented (13%) |
| Flow changes | 2 | Orchestrator pipeline well-established but linear |
| New agents | 0 | No agent infrastructure |
| Eval improvements | 1 | Standard auto-generated eval |
| Knowledge management | 2 | Vault notes exist, no structured archival |
| Infrastructure | 2 | No CI/CD, manual remote execution |
| Operational execution | 2 | Level 3 builds proven locally |

**Underserved dimensions:** Operational execution, Instrumentation, Infrastructure

## Anti-patterns Identified
1. Naive byte-for-byte JAR comparison → 100% false DIVERGENT verdicts
2. `javap -c` for bytecode diffing → 1100+ lines of false-positive diff per class from constant pool indices
3. Sequential builds on one node → parallelize across 3 rh-h100 nodes
4. Ignoring test env issue → `ModuleNotFoundError: No module named 'buildroot'`; must `pip install -e .`
5. Hardcoded JAR paths → use `find` as fallback for multi-module builds
6. Comparing `.properties` timestamps → strip comment lines before comparison

## Builder Instructions
- Mixed hypothesis: use --timeout 1800 (generous for remote builds)
- Must fix module import issue in test env AND implement comparison pipeline
- Remote execution on rh-h100 nodes will take significant time

## Score Context
- Current composite: ~0.30 (weighted: tests=0.0, lint=1.0, type_check=0.4, coverage=0.0, observability=0.1)
- Note: tests/coverage at 0.0 due to `ModuleNotFoundError` environment issue, not code defects
- Prior eval (post-experiment #001): 0.8499
