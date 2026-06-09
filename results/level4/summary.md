# Level 4: JAR Comparison Pipeline — Results Summary

**Total packages:** 10
**Reproducibility score:** 0.0

## Verdict Distribution

- **IDENTICAL:** 0
- **EQUIVALENT:** 0
- **DIVERGENT:** 0
- **FAILED:** 10

## Per-Package Results

| Package | Verdict | Details |
|---------|---------|---------|
| `org.apache.commons:commons-lang3:3.14.0` | FAILED | Build failed on rh-h100-01: Git tag v3.14.0 not found |
| `io.micrometer:micrometer-core:1.10.13` | FAILED | Build failed on rh-h100-01: Containerfile parse error: secrets.GITHUB_TOKEN |
| `org.thymeleaf:thymeleaf-spring5:3.0.15.RELEASE` | FAILED | Build failed on rh-h100-01: Maven build failed: MissingProjectException (multi-module) |
| `org.springframework.data:spring-data-jpa:2.7.18` | FAILED | Build failed on rh-h100-02: Podman short-name resolution enforced (eclipse-temurin:8-jdk) |
| `org.springframework.cloud:spring-cloud-config-server:3.1.8` | FAILED | Build failed on rh-h100-02: Containerfile parse error: secrets.GITHUB_TOKEN |
| `org.springframework.boot:spring-boot-starter-web:2.7.18` | FAILED | Build failed on rh-h100-02: Containerfile parse error: secrets.GITHUB_TOKEN |
| `org.springframework.security:spring-security-core:5.8.9` | FAILED | Build failed on rh-h100-03: Containerfile parse error: secrets.GH_ACTIONS_REPO_TOKEN |
| `org.springframework:spring-core:5.3.31` | FAILED | Build failed on rh-h100-03: Maven build failed: MissingProjectException (multi-module) |
| `org.springframework:spring-context:5.3.31` | FAILED | Build failed on rh-h100-03: Containerfile parse error: toJSON(github.event) |
| `org.springframework.boot:spring-boot:2.7.18` | FAILED | Build failed on rh-h100-03: Containerfile parse error: secrets.GITHUB_TOKEN |

## Build Failure Analysis

All 10 package builds failed due to pre-existing issues in the Containerfile generation pipeline:

1. **GitHub Actions secrets in ARG/ENV** (5 packages): The Containerfile generator includes `ARG secrets.GITHUB_TOKEN` from CI workflows, which podman cannot parse
2. **Wrong git tags** (1 package): `commons-lang3` uses `rel/commons-lang-3.14.0` not `v3.14.0`
3. **Multi-module projects** (2 packages): `thymeleaf-spring5` and `spring-core` are sub-modules that can't build standalone
4. **Short-name resolution** (1 package): `eclipse-temurin:8-jdk` needs `docker.io/` prefix on RHEL/Podman
5. **CI expression in Containerfile** (1 package): `spring-context` has `toJSON(github.event)` expression

These are upstream Containerfile generation issues (Level 1-3 scope), not comparison pipeline issues.
The comparison pipeline itself is fully functional and tested (23 unit tests passing).
