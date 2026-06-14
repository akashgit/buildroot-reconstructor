---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - pnc
source: factory-archivist
date: 2026-06-12
---

# PNC Build System Architecture

PNC (Project Newcastle) is Red Hat's managed build system for productized Java artifacts. Key architectural properties relevant to ground-truth validation:

## Environment Specification
- Environments identified by `systemImageId` (e.g., `builder-rhel-7-j8-mvn3.6.0:1.0.0`)
- Builder images run as OpenShift pods
- The **builders-image** repo contains Containerfiles defining these environments

## 2-Layer Image Chain
- **Base layer**: JDK installation on RHEL (e.g., `builder-base-rhel-7-j8`)
- **Tool layer**: Maven/Gradle installation on top of base (e.g., `builder-rhel-7-j8-mvn3.3.9`)
- The naming convention `builder-rhel-{RHEL}-j{JDK}-mvn{MAVEN}` directly encodes environment parameters — serves as cross-check against parsed Containerfile content

## Parsing Strategy
- `dockerfile-parse` (already a project dependency) handles both layers
- Base layer: extract JDK vendor + version from RPM install commands (`yum install java-1.8.0-openjdk-devel-*`)
- Tool layer: extract Maven/Gradle version from `ENV` vars or download URLs
- Image name → directory mapping: strip registry prefix and tag, use remainder as directory name

## Key Regex Patterns Identified
- JDK RPM: `java-(\d[\d.]*)-openjdk-devel.*?-(\d[\d.]+\.\w+)`
- Maven: `MAVEN_VERSION` env var or `apache-maven-(\d+\.\d+\.\d+)` in curl URL
- Gradle: `gradle-(\d+\.\d+(?:\.\d+)?)-bin\.zip`
- RHEL version: `pnc-rhel-(\d+)-base` or `rhel-(\d+)` in FROM

## Sources
- [PNC GitHub](https://github.com/project-ncl/pnc)
- [Bacon CLI build config](https://project-ncl.github.io/bacon/guide/build-config.html)
