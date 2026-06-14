---
tags:
  - factory
  - strategy
  - buildroot-reconstructor
date: 2026-06-13
source: factory-archivist
---

# Strategy: buildroot-reconstructor — 2026-06-13

## Cycle 5 Summary: PNC Validation Execution

### Experiment Run
- **#005** (KEEP) — Tier 1 operational refinement: execute PNC validation on rh-h100-01

### Results
- Mean accuracy: 0.5833 across 3 Maven packages
- Best: jackson-core:2.17.0 at 0.750 (JDK 8 matched PNC)
- Worst: commons-lang3:3.14.0 at 0.325 (JDK 21 vs PNC's JDK 8 — Build-Jdk-Spec misleading)
- Middle: snakeyaml:2.2 at 0.675 (JDK 11 matched, Maven version missing)

### Key Discovery
Build-Jdk-Spec in JAR manifests reports the JDK used by upstream CI (e.g., GitHub Actions), NOT the JDK used by PNC for its reproducible build. This is a fundamental limitation of the current heuristic for PNC validation purposes. When the upstream project uses a different JDK than PNC, the reconstructor's inference will always mismatch.

### Accuracy Baseline Established
The 0.5833 mean provides a quantitative target for future improvement experiments. The dimension breakdown shows:
- **Build tool detection**: Strong (Maven detected correctly across all 3)
- **JDK version inference**: Weak when upstream CI differs from PNC
- **OS family extraction**: Missing (empty string across all packages)
- **Maven version extraction**: Inconsistent (missing for snakeyaml)

### Keep Streak
5 experiments, 5 keeps, 0 reverts. Project has maintained a perfect record.

### What's Next
Accuracy improvement experiments targeting:
1. PNC image name parsing as authoritative JDK source
2. OS family extraction from base image
3. Maven version extraction completeness
