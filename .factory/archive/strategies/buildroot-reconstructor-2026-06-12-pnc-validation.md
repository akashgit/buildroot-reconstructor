---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-12
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-12

## Context
- **Composite Score**: 0.8500 (179 tests passing, 3/3 experiments kept)
- **Cycle**: 4 (PNC ground-truth validation)
- **Prior Cycle**: Level 4 JAR comparison pipeline — complete, 50% equivalence rate
- **CEO Verdict**: PROCEED — PLAN APPROVED

## Strategist Design Space Assessment

| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | 10 core features, 13-step pipeline, Level 4 comparison done |
| Bug fixes | 3 | Zip-slip, shell injection, resource leak all fixed |
| Instrumentation | 1 | 13% function coverage, no tracing, 35% observability score |
| Flow changes | 2 | Pipeline stable; no architectural changes |
| Eval improvements | 2 | Standard hygiene eval; no project-specific eval dimensions |
| Knowledge management | 3 | 5 vault notes, patterns.md maintained |
| Infrastructure | 2 | rh-h100-01 builds working, no CI/CD |
| Operational execution | 3 | Level 3 10/10, Level 4 5/10 EQUIVALENT |

**Underserved dimensions**: Instrumentation, Eval improvements, Infrastructure

## Approved Hypothesis

### H1: PNC Ground-Truth Validation (EXPLORE, mixed, capability_surface)
- **Addresses**: Issue #9 — PNC ground-truth validation
- **Category**: EXPLORE
- **Expected impact**: capability_surface +0.15

**5 Deliverables:**
1. **PNC Containerfile parser** (`src/buildroot/parsers/pnc_containerfile.py`) — Parse 2-layer PNC Containerfiles using `dockerfile-parse`, extract JDK/Maven/RHEL versions from RPM installs and ENV directives
2. **Accuracy scorer** (`src/buildroot/utils/accuracy_scorer.py`) — 6-dimension weighted comparison (JDK major 0.25, build tool 0.25, tool version 0.15, SCM 0.15, JDK vendor 0.10, OS family 0.10)
3. **Validation pipeline CLI** (`src/buildroot/cli/commands/validate.py`) — `buildroot validate` subcommand wired into main CLI
4. **Report generator** — JSON results to `results/pnc-validation/report.json`
5. **Tests** — Synthetic PNC Containerfile fixtures, parser + scorer test suites

**Execution**: Run on rh-h100-01 against 3 packages:
- commons-lang3:3.14.0 (JDK 8/Maven 3.3.9)
- jackson-core:2.17.0 (JDK 8/Maven 3.3.9)
- snakeyaml:2.2 (JDK 11/Maven 3.6.3)

**Expected accuracy**: 0.35–0.55 per package (JDK version mismatches expected — Build-Jdk-Spec reflects upstream CI, not PNC)

## CEO Notes for Builder
- SSH to rh-h100-01 for validation runs
- builders-image repo at `~/factory-projects/buildroot-reconstructor/builders-image/`
- Use `-k/--insecure` for Red Hat internal endpoints
- commons-lang3 already EQUIVALENT in Level 4
- Use `dockerfile-parse` (already a dependency)

## Key Anti-Patterns
- Don't over-engineer the scorer — exact matches with simple weights
- Don't parse Containerfiles with raw regex — use `dockerfile-parse`
- Don't treat JDK mismatches as bugs — they're expected findings
- Don't try to build PNC images — parse only, they depend on internal RHEL infra
- Don't block on all 20 packages — 3 this cycle, scale later

## Pattern Observed
3/3 experiments kept across 3 cycles. Project is mature (13-step pipeline, 10/10 Level 3, 50% Level 4). Shifting from self-referential validation to external benchmark (PNC ground truth) — first accuracy measurement against independently known build environments.
