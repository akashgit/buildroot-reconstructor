The research report is complete at `results/outer-loop-full/cycle_004/research_report.md`.

## Key Findings

The "unknown" error class masking 2/3 failed packages decomposes into **four concrete, fixable root causes**:

| Root Cause | Impact | Fix Complexity |
|---|---|---|
| **Gradle misidentification** — both packages are Gradle projects, system only supports Maven | Blocks both packages entirely | Medium (observer + template changes) |
| **Containerfile extraction death spiral** — no immutable anchor fallback in loop.py | 27/30 iterations wasted | Low (3-line change) |
| **Tag format mismatch** — spring-security uses `5.8.9` not `v5.8.9` | 4/15 iterations wasted | Low (git ls-remote lookup) |
| **Obsolete JVM flag** — `-XX:MaxPermSize=2048m` in spring-security's gradle.properties | Crashes JDK 9+ builds | Low (sed in template) |

**Critical discovery from repo inspection:**
- **micrometer-core** = Gradle 8.4, multi-module, submodule `:micrometer-core` depends on `:micrometer-commons` + `:micrometer-observation`, targets JDK 8 but needs JDK 11+ for multi-release JAR
- **spring-security-core** = Gradle 7.5.1, submodule at `core/` (referenced as `:core`), build file is `spring-security-core.gradle`, has the `MaxPermSize` poison pill

**Top recommendation for Strategist:** The P0 fix is adding **Gradle build system detection** in the observer and an **anchor fallback** in loop.py. These two changes together address the root cause of both failing packages and prevent the death spiral that wastes 90% of compute budget. Expected solve rate improvement: 0.33 → 0.67-1.0.
