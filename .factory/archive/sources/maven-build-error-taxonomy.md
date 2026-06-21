---
tags:
  - factory
  - source
  - build-repair
  - maven
source: factory-archivist
date: 2026-06-13
---

# Maven Build Error Taxonomy

**Sources:**
- [Practitioner taxonomy](https://reintech.io/blog/resolving-common-maven-build-errors)
- [Hassan's CI failure taxonomy](https://foyzulhassan.github.io/files/DoctoralSymp_ASE.pdf)

## Findings

Common Maven failure categories (ranked by frequency):
1. Dependency resolution failures (most common)
2. Plugin configuration issues
3. Compilation errors (JDK mismatches)
4. Memory issues (OOM in large builds)
5. Environment issues (31/91 in Hassan's taxonomy)

Our spec's taxonomy aligns well with the literature. Missing from our taxonomy: `environment_error/github_actions_expression` — exp #003 showed 5/10 failures from unstripped `${{ secrets.* }}`.

## Relevance to Buildroot Reconstructor

Seeds the Analyzer's error classification. From exp #003's 10 failed builds, the concrete taxonomy is:

| Error Class | Count | Fix Direction |
|-------------|-------|--------------|
| `environment_error/gha_secrets` | 5 | Strip `${{ secrets.* }}` from ENV/ARG |
| `environment_error/gha_expressions` | 2 | Strip `${{ toJSON() }}`, `${{ github.* }}` |
| `source_error/wrong_tag` | 1 | Try alternate tag formats |
| `build_tool_error/multi_module` | 1 | Add `-pl` flag, install parent first |
| `environment_error/image_resolution` | 1 | Use fully-qualified `docker.io/` prefix |

## Key Takeaway

GHA expression sanitization alone fixes 7/10 failures. This should be a pre-flight fix in the Observer/Builder before the iterative loop even starts. The Analyzer's regex-based classification handles the majority; LLM fallback only needed for novel errors.
