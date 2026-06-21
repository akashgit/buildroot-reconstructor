---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level3
source: factory-archivist
date: 2026-06-08
---

# Git Tag Format Discovery

## Finding

The orchestrator hardcodes `git_tag=f"v{version}"` (line 154 in `orchestrator.py`). Real tag formats vary wildly across Maven projects.

## Tag Format Variation

| Project | Actual tag format | v{version} guess | Correct? |
|---------|------------------|-------------------|----------|
| Apache Commons Lang | `rel/commons-lang-3.14.0` | `v3.14.0` | NO |
| Spring Boot | `v2.7.18` | `v2.7.18` | YES |
| Spring Framework | `v5.3.31` | `v5.3.31` | YES |
| Thymeleaf | `thymeleaf-spring5-3.0.15.RELEASE` | `v3.0.15.RELEASE` | NO |
| Micrometer | `v1.10.13` | `v1.10.13` | YES |
| Spring Data JPA | varies | `v2.7.18` | UNCERTAIN |

## Recommended Fix (from BuildGen paper)

1. List tags from GitHub API
2. Match version string against tag names using regex patterns
3. Prefer shorter prefixes; favor prefixes that are substrings of artifactId
4. Common patterns: `v{version}`, `{artifactId}-{version}`, `rel/{artifactId}-{version}`, bare `{version}`

## Key Insight

`v{version}` works for Spring ecosystem (majority of test set) but fails for Apache projects (different convention) and Thymeleaf (module-prefixed tags). A tag discovery heuristic is essential for generalization beyond Spring.
