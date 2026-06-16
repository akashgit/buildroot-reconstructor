The research report is complete at `results/outer-loop-full/cycle_002/research_report.md`.

## Key Findings

The `unknown` error class was hiding **three distinct, well-understood root causes**:

### 1. Containerfile Extraction Death Spiral (87% of failures — STILL ACTIVE)
The cycle 1 fix was **ineffective** due to two remaining bugs:
- **`DockerfileParser` is too lenient** — it accepts prose as valid Dockerfiles, so prose passes L1 but fails at L2 (podman) with "stage 1 requires a FROM instruction"
- **Fallback cascading corruption** — once the Containerfile variable becomes prose, every subsequent `_validate_containerfile` fallback is also prose. No recovery path exists.

### 2. Both Packages Use Gradle, Not Maven (undetected by observer)
- **micrometer-core** → Gradle 8.4, `./gradlew`, multi-module, targets JDK 8
- **spring-security-core** → Gradle 7.5.1, `./gradlew`, multi-module, `core/` subdir

The observer generates `RUN mvn clean install` which immediately fails.

### 3. Spring Security has `-XX:MaxPermSize=2048m` in gradle.properties
This obsolete JVM flag (removed in JDK 9) crashes the Gradle daemon on modern JDKs. Needs `sed` removal or JDK 8.

### Priority Fixes for Strategist
1. **P0**: Add structural FROM validation in `_l1_parse()` (catches prose before podman)
2. **P0**: Maintain the observer's template as an immutable fallback anchor (breaks death spiral)
3. **P0**: Add build system detection (`build.gradle`/`gradlew` → Gradle template)
4. **P1**: Add `sed` for obsolete JVM flags + `environment/obsolete_jvm_flag` error pattern
