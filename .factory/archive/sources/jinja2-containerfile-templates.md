---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
---

# Jinja2 Containerfile Templates — Two-Pattern Approach

## Finding

Two Dockerfile/Containerfile template patterns are needed, selected based on whether system packages are required.

## Pattern 1: JDK Base Image (`jdk_base.Containerfile.j2`)

Used when no OS-level system packages are needed. Uses vendor-specific JDK base images directly:

| distribution | Container image pattern |
|---|---|
| `temurin` | `eclipse-temurin:{{version}}-jdk-jammy` |
| `corretto` | `amazoncorretto:{{version}}` |
| `zulu` | `azul/zulu-openjdk:{{version}}` |
| `liberica` | `bellsoft/liberica-openjdk-debian:{{version}}` |
| `oracle` | `container-registry.oracle.com/java/openjdk:{{version}}` |

Maven installed via `curl` from `archive.apache.org`.

## Pattern 2: JDK on Ubuntu (`jdk_on_ubuntu.Containerfile.j2`)

Used when system packages or a specific OS version is needed. Starts from `ubuntu:{{version}}`, then installs JDK via vendor-specific APT repos (Adoptium for Temurin, apt.corretto.aws for Corretto).

## Template Selection Logic

- If `system_packages` list is non-empty → Pattern 2
- If CI workflow uses a specific `runs-on` Ubuntu version → Pattern 2
- Otherwise → Pattern 1

## Reference

Adoptium containers project (`github.com/adoptium/containers`) uses the same Jinja2 approach for multi-version/multi-distro matrix generation.
