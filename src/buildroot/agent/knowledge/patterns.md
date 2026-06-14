# Build Patterns Knowledge Base

## Spring Boot

- Spring Boot projects use `spring-boot-maven-plugin` for packaging
- Require `mvn package -DskipTests` to produce executable JARs
- Often need `-Dgpg.skip=true` to avoid GPG signing in CI
- Multi-module Spring projects need parent install first: `mvn install -N`

## Multi-Module

- Use `-pl <module>` to build specific modules
- Install parent POM first with `mvn install -N -DskipTests`
- Reactor ordering matters: dependencies must be built before dependents
- Non-resolvable parent POM usually means parent needs to be installed first

## Jackson / JSON Libraries

- Jackson modules often require `jackson-bom` import for version management
- Use `mvn package -DskipTests -Dgpg.skip=true`
- Annotation processor modules need `-Dgenerate-sources` in some builds

## Apache Commons

- Typically straightforward single-module builds
- Use standard `mvn package -DskipTests`
- JDK version specified in `maven.compiler.source` / `maven.compiler.target`
- commons-lang3 solved in 1 iteration — a baseline reference

## Standalone JAR

- Simple Maven projects with single artifact output
- Default build: `mvn package -DskipTests`
- JDK version from POM properties or `Build-Jdk-Spec` manifest entry

## General Patterns

- GHA expression sanitization (`${{ }}`) fixes ~70% of initial parse failures
- Pre-flight sanitization beats iterative repair for known error classes
- Use fully-qualified image names: `docker.io/library/maven:3.9-eclipse-temurin-17`
- `Build-Jdk-Spec` reflects upstream CI JDK, not PNC build JDK
