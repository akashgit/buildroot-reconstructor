---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-08
---

# Maven CI/CD Transparency Ceiling — 84% Opaque

## Finding

Approximately 84% of the top 1,200 commonly used Maven artifacts are NOT built using a transparent CI/CD pipeline. This stat comes from the BuildGen/AROMA research ecosystem.

## Implication for Buildroot Reconstructor

CI workflow parsing (GitHub Actions, CircleCI) — currently our strongest signal source — has an inherent ceiling. It works well for open-source Spring ecosystem projects but fails for the majority of Maven Central artifacts.

## Required Fallback Strategy

For the 84% without transparent CI:
1. POM SCM fields for source repo discovery
2. JAR manifest (Build-Jdk-Spec) for actual build JDK
3. POM plugin analysis for build command inference
4. Maven Wrapper properties for Maven version
5. deps.dev / Google OSI API for source repo lookup

## Current State

Our test set is biased toward the 16% — 6 of 10 packages are Spring ecosystem with public CI. commons-lang3 and thymeleaf represent the harder 84% case. Level 3 success on these two packages validates the fallback strategy.
