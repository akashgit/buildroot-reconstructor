The research report is complete at `results/outer-loop-full/cycle_001/research_report.md`.

## Summary

The "unknown" error classification was masking **three distinct, well-understood failure modes**:

| Root Cause | Frequency | Fix |
|---|---|---|
| **Containerfile output corruption** — Claude returns markdown prose wrapping the Containerfile, but `_extract_containerfile()` only strips leading code fences | 27/30 attempts (90%) | Robust regex extraction + FROM-line detection + validation guard |
| **Gradle misidentified as Maven** — both failed packages (micrometer, spring-security) are Gradle projects | 2/30 attempts | Build system detection + Gradle template |
| **Error taxonomy gap** — no patterns for `stage 1 requires FROM`, `no POM in directory`, `gradle: not found` | All 30 | Add `containerfile/parse_error` and `build_tool/wrong_build_system` classes |

**Key insight:** The system was stuck in a death spiral — the corrupted Containerfile (with prose) became the input for the next Claude call, which returned another prose-wrapped response, which was again corrupted. 27 of 30 iterations were completely wasted on the same extraction bug. A single robust `_extract_containerfile()` implementation would have prevented this cascade entirely.

**Priority recommendations for the Strategist:**
1. **P0:** Harden `_extract_containerfile()` with multi-strategy extraction (regex code blocks → FROM-line scan → fallback)
2. **P0:** Add validation guard in the loop to reject outputs not starting with valid Dockerfile instructions
3. **P1:** Add Gradle build system detection and `gradle_base.j2` template
4. **P2:** Expand the error taxonomy with the two new error classes
