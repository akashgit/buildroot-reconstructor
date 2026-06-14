---
tags:
  - factory
  - source
source: factory-archivist
date: 2026-06-07
---

# Maven Property Resolution Challenges

## Key Technical Findings

### Property Resolution Order (precedence)
1. System properties (`-Dkey=value`)
2. Project properties (`${project.version}`, `${project.groupId}`)
3. Settings properties (from `~/.m2/settings.xml`)
4. Environment variables (`${env.JAVA_HOME}`)
5. POM-defined properties (`<properties>` block)

### Critical Complication
Properties resolve **after** inheritance. A child POM can override a parent's property, changing the behavior of parent-defined plugin configurations. Must:
1. Build full inheritance chain (child → parent → grandparent → super POM)
2. Merge properties top-down
3. Then resolve `${...}` placeholders

### CI-Friendly Versions (Maven 3.5.0+)
`${revision}`, `${sha1}`, `${changelist}` are set via command-line args in CI, not in POM. These are inherently unresolvable from POM analysis alone.

### JDK Version vs. Language Level
`maven.compiler.source` specifies **language level**, not JDK version. Source level 11 can compile on JDK 17. CI workflow is where the real JDK selection happens — POM analysis alone is insufficient.

### Multi-Level Inheritance (common in Spring)
Example: `spring-boot-starter-web` chains through 4 levels of parent POMs. Each level adds properties, plugin configurations, and dependency management.

## Impact on Design

These challenges drove the priority heuristic in JDK inference (CI > POM) and the gap detection system (confidence levels for every inferred value).
