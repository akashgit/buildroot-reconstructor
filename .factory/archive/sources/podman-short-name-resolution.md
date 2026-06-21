---
tags:
  - factory
  - source
  - infrastructure
source: factory-archivist
date: 2026-06-16
---

# Podman Short-Name Resolution — docker.io/library/ Prefix Requirement

**Sources**: [Podman docs](https://docs.podman.io/en/latest/markdown/podman-pull.1.html), [Red Hat blog](https://www.redhat.com/en/blog/container-image-short-names)

## The Problem

- **Docker**: `eclipse-temurin:17-jdk` → implicitly resolves to `docker.io/library/eclipse-temurin:17-jdk`
- **Podman**: Requires either (a) explicit `docker.io/library/` prefix, (b) configured `unqualified-search-registries`, or (c) a short-name alias

## Three Short-Name Modes

1. **Enforcing** (default): Prompts user to select registry if no alias exists. **Fails without TTY** — exactly our containerized build environment
2. **Permissive**: Tries all search registries, no alias recorded
3. **Disabled**: Tries all registries, no prompting

## Impact on Buildroot

Caused **5 of 12 L2 failures** in exp 9 (kafka-clients, assertj-core, json-smart, protobuf-java, hibernate-validator). The fix is deterministic and definitive: always emit fully-qualified image names.

## Security Consideration

Red Hat warns that short names risk "hitting squatted registry namespaces" — an attacker could register the same image name on a different registry. Fully-qualifying is the security-recommended approach regardless of runtime.

## Implementation

Single function change in `_map_distribution_to_image()` (jdk.py:299-304) — prepend `docker.io/library/` for Docker Hub official images. Zero-cost, no behavioral change for Docker users.

## Known Issues

[Podman issue #13234](https://github.com/containers/podman/issues/13234): even fully-qualified names sometimes fail with short-name errors in docker-compose contexts. Workaround: ensure `registries.conf` has `unqualified-search-registries = ["docker.io"]`, but proper fix is fully-qualifying in the Containerfile itself.
