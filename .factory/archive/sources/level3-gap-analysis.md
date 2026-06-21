---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level3
source: factory-archivist
date: 2026-06-08
---

# Level 3 Full Rebuild — Gap Analysis

Research phase identified 7 critical gaps blocking Level 3 (full source rebuild inside container) for the 10 test packages. All 80 Level 1+2 tests pass (70 inference + 10 podman build), but Level 3 requires: source acquisition, correct tag checkout, correct build JDK, and correct build command.

## Gap Taxonomy (by priority)

| # | Gap | Severity | Packages Blocked |
|---|-----|----------|-----------------|
| 1 | No source code acquisition (templates use COPY . .) | CRITICAL | All 10 |
| 2 | Source repo discovery broken (SCM XML parsing is dead code) | CRITICAL | commons-lang3, thymeleaf, micrometer |
| 3 | Git tag format hardcoded to v{version} | CRITICAL | commons-lang3, thymeleaf |
| 4 | JDK = language level, not build JDK | HIGH | commons-lang3 (needs 21, gets 8), thymeleaf (needs 11, gets 8) |
| 5 | Build command defaults to `mvn clean install -B` | MEDIUM | commons-lang3, thymeleaf |
| 6 | Maven version not inferred from wrapper | LOW-MEDIUM | Reproducibility concern |
| 7 | project.build.outputTimestamp not handled | LOW | Bit-for-bit reproducibility |

## Key Insight

Gaps 1-3 are sequential blockers — fixing source acquisition (Gap 1) is useless without fixing repo discovery (Gap 2) and tag format (Gap 3). The CEO directed the Strategist to bundle Priorities 1-5 into a single hypothesis.

## CEO Verdict

PROCEED — gap taxonomy well-structured, priority ordering correct. Strategist to generate one bundled hypothesis covering Priorities 1-5.
