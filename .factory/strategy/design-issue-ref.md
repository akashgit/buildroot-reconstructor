# Agent System v3 — Design Issue Reference

**Issue:** [#51 — Agent System v3: Comprehensive Design](https://github.com/akashgit/buildroot-reconstructor/issues/51)
**Created:** 2026-06-19
**Source:** Synthesis of issue #48 (body + 3 comments), experiments #9-16, research-context.md (113 requirements)

---

## 8 Implementation Phases

| Phase | Title | Scope | Key Requirements |
|-------|-------|-------|-----------------|
| P1 | Data Models + Pre-Pass | PrePassFindings, schema extensions, run_prepass() | E1-E9, I1-I4, D9, D12, D16 |
| P2 | Analysis Agent Enhancement + Evaluator Bug Fix | Full tool access, enhanced prompts, diff_summary fix | A1, D1, D3, D5-D7, D13, J2 |
| P3 | Feedback Loop + Loop Control | Elitist gate, dead-end tracking, structured feedback, stagnation/oscillation | G1-G11, G13, H5-H6, H8, D10, D17 |
| P4 | Multi-Signal Fallback Scoring | ScoreBreakdown, fallback signals, graceful degradation | F1-F7, A2, H3-H4, J4 |
| P5 | CLI Integration + Pipeline Wiring | --pipeline v3 flag, batch support | J3, B10 |
| P6 | Optimizations | Cross-package transfer, warm-start, parallel builds, multi-variant | D8, D15, G12, G14, H9 |
| P7 | Benchmark + Default Switch | Full 31-package benchmark, v3 becomes default | J5 |
| P8 | Cleanup Deprecated Components | Remove Observer, GapDetector, Node Agents, AnalyzeAgent | C3-C4, C6, C8, J6 |

---

## 4-Tier Test Plan

| Tier | What | Runtime | When to Run |
|------|------|---------|-------------|
| T1 | Unit tests (~560 tests, all mocked) | < 1 second | Every commit, every PR |
| T2 | Fast E2E smoke (jettison:1.5.4 on rh-h100-01) | ~7 minutes | After ANY agent/pipeline code change |
| T3 | Fast subset (7 packages covering all failure tiers) | ~30 minutes | Before merging any phase PR |
| T4 | Full 31-package benchmark | ~5.5 hours | Once at migration end (Phase 7) |

**Fast subset packages (Tier 3):** jackson-databind (L4 guard), snappy-java (L4 multi-iter guard), jackson-core (L3 cross-package), commons-beanutils (L3 Apache), lz4-java (L2 Gradle), kafka-clients (L2 podman), hibernate-core (L1 stress test)
