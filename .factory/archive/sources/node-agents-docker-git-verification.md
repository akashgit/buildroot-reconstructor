---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-24
  - docker
  - git
source: factory-archivist
date: 2026-06-15
research-type: external
---

# Docker Hub Tag Verification & Git Tag Discovery Patterns

## Docker Hub Registry API

### Tag Verification

Fastest method: HEAD request to OCI Distribution Spec manifests endpoint.

```
HEAD /v2/<namespace>/<name>/manifests/<tag>
```
- 200 OK → tag exists
- 404 → tag does not exist
- Requires bearer token from `auth.docker.io/token`

### Authentication Flow
1. Get token: `GET https://auth.docker.io/token?service=registry.docker.io&scope=repository:<name>:pull`
2. HEAD request with `Authorization: Bearer <token>`

### Rate Limits
- Anonymous: 100 pulls/6hr
- Authenticated: 200 pulls/6hr
- For node agents: cache token and reuse within a pipeline run

### Tag Listing
`GET /v2/<name>/tags/list` — paginated, follow `Link` headers for images with many tags.

## Git Tag Discovery

### Core Pattern
```bash
git ls-remote --tags --refs https://github.com/{owner}/{repo} 'v*'
```

### Version Tag Patterns (inconsistent across projects)
| Pattern | Example | Usage |
|---------|---------|-------|
| `v{version}` | `v3.14.0` | Most common (Spring, Apache Commons) |
| `{artifactId}-{version}` | `commons-lang3-3.14.0` | Apache multi-module |
| `rel/{artifactId}-{version}` | `rel/commons-lang3-3.14.0` | Some Apache projects |
| `{version}` | `3.14.0` | No prefix |

### Edge Cases
- Annotated vs lightweight tags: always use `--refs` to exclude peeled `^{}`
- Monorepo tags: Spring Framework uses `v5.3.18` for entire repo, not per-module
- Tags on forks: may include parent repo tags
- Release branches vs tags: some projects use `release/v1.0` branches

## Container Base Image Tag Conventions

### Eclipse Temurin (most common)
Pattern: `eclipse-temurin:<java-version>-<jdk|jre>[-<os-codename>]`
- `21-jdk` = Ubuntu (default, changes over time)
- `21-jdk-jammy` = Ubuntu 22.04 (explicit, reproducible)
- `21-jdk-alpine` = Alpine Linux

**Bug found:** Current `DISTRIBUTION_IMAGE_MAP` produces `eclipse-temurin:21` (missing `-jdk` suffix). Canonical form is `eclipse-temurin:21-jdk`.

### Other Vendors
- **Liberica**: OS in repo name (`bellsoft/liberica-openjdk-debian`), version in tag
- **Corretto**: `amazoncorretto:<ver>[-alpine]`
- **Zulu**: OS in repo name (`azul/zulu-openjdk[-alpine]`), version in tag

## Sources
- [Docker Registry API — Baeldung](https://www.baeldung.com/ops/docker-registry-api-list-images-tags)
- [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec/blob/main/spec.md)
- [Git ls-remote Documentation](https://git-scm.com/docs/git-ls-remote.html)
- [Eclipse Temurin Container Images — Adoptium](https://adoptium.net/installation/containers)
- [Liberica JDK Container Images — BellSoft](https://bell-sw.com/libericajdk-containers/)
