---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level3
source: factory-archivist
date: 2026-06-08
---

# SCM Source Repository Discovery — Dead Code Path

## Finding

The `discover_repo_from_pom()` function in `github_api.py` has a dead code path for SCM extraction (lines 92-96 — the loop body is `pass`). It does NOT extract `<scm><url>`, `<scm><connection>`, or `<scm><developerConnection>` from POM XML.

## Impact

commons-lang3 gets **empty `source_repo`** despite the POM containing `<scm><url>https://gitbox.apache.org/repos/asf?p=commons-lang.git</url></scm>`. Only Spring packages work because they have hardcoded mappings.

## What Currently Works

- `project.scm.url` property lookup (rarely populated as a flat property)
- `maven-scm-plugin` configuration (rare)
- Hardcoded Spring project mappings (covers 4 patterns only)

## What Must Be Added

1. Parse `<scm>` XML element from POM directly (url, connection, developerConnection)
2. Parse `<url>` element (project URL, often GitHub link)
3. Query deps.dev / Google OSI API as fallback
4. Support non-GitHub repos (gitbox.apache.org, gitlab, bitbucket)

## Per-Package Status

| Package | source_repo | Root cause |
|---------|-------------|------------|
| commons-lang3 | EMPTY | No SCM XML extraction |
| thymeleaf-spring5 | LIKELY EMPTY | No SCM, no mapping |
| micrometer-core | LIKELY EMPTY | No SCM, no mapping |
| spring-boot/core/security/data/cloud | Working | Hardcoded mapping |

## Research Grounding

BuildGen (arXiv:2509.08204) uses: SLSA provenance → POM SCM fields → deps.dev API. AROMA (ACM 2024) also uses SCM fields as primary source detection.
