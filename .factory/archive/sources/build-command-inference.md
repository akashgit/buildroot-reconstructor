---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level3
source: factory-archivist
date: 2026-06-08
---

# Build Command Inference from POM Plugins

## Finding

When no CI workflow is discovered (commons-lang3, thymeleaf), the build command defaults to `mvn clean install -B`. This naive default fails because projects require specific plugins, profiles, and skip flags.

## Common Failure Modes

- **Apache RAT** plugin: license header checks fail without `-Drat.skip=true`
- **GPG plugin**: signature generation fails without keys → needs `-Dgpg.skip=true`
- **Maven Wrapper**: projects with `./mvnw` should use it instead of system `mvn`
- **Profiles**: some projects need `-Papache-release` or other profiles
- **Multi-module**: may need `-pl <module>` or reactor ordering

## Reproducible Central Buildspec Standard

The de facto standard `.buildspec` captures the exact build command:
```
command="mvn -Papache-release clean package -DskipTests -Dmaven.javadoc.skip -Dgpg.skip"
```

## Fix Approaches

1. Detect maven-wrapper-plugin in POM → use `./mvnw`
2. Detect `.mvn/wrapper/` directory in source repo → use `./mvnw`
3. Detect Apache RAT plugin → add `-Drat.skip=true`
4. Detect GPG plugin → add `-Dgpg.skip=true`
5. For packages with CI: extract the actual build command (already done)
6. For packages without CI: use smarter default based on POM plugin analysis

## Key Stat

84% of the top 1,200 commonly used Maven artifacts are NOT built using a transparent CI/CD pipeline. This means CI-based inference has an inherent ceiling — POM analysis + JAR manifest inspection is essential.
