---
tags:
  - factory
  - source
  - build-repair
source: factory-archivist
date: 2026-06-13
---

# CI-Repair-Bench: Automated CI Build Repair

**Paper:** [CI-Repair-Bench](https://arxiv.org/html/2604.27148)

## Findings

Automated repair works best for localized, tool-enforced failures (linting, formatting) and worst for environment/dependency/configuration failures. Best LLM achieves only 18.9% repair success rate on CI failures.

Key insight: Containerfile repair is harder than source code repair because errors are indirect — a JDK version mismatch manifests as a compilation error, not a version error.

## Relevance to Buildroot Reconstructor

Sets realistic expectations for our inner loop. Our domain (Containerfile repair for build reproduction) is harder than general CI repair because:
1. Errors are indirect (environment -> build failure)
2. Ground truth is not test suites but JAR byte-level comparison
3. The search space includes base images, JDK versions, Maven versions, env vars, and build flags

The 18.9% baseline means our iterative approach (multiple attempts with feedback) is essential — single-shot repair will not work for our domain.

## Key Takeaway

Our error taxonomy must map indirect errors to root causes. The Analyzer's pattern matching for common Maven errors, followed by LLM fallback for ambiguous cases, is the right architecture given these findings.
