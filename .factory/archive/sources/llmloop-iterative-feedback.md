---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - outer-loop
source: factory-archivist
date: 2026-06-13
---

# LLMLOOP: Iterative Feedback Loops for LLM-Generated Code

**Source**: [LLMLOOP: Improving LLM-Generated Code and Tests](https://arxiv.org/html/2603.23613v1) (ICSME 2025)

## Key Findings for Outer Loop

### Per-Error-Type Feedback Loops
Five dedicated feedback loops for different error types (compilation, static analysis, test failures, etc.), each with its own prompt template. Different failure modes benefit from different prompts.

### Dynamic Temperature Adjustment
Temperature varies based on the type and severity of the error being addressed. Relevant for the outer loop Builder when generating code changes — exploratory changes may benefit from higher temperature.

### Mapping to Our Architecture
Our Failure Analyst's taxonomy naturally creates per-error-class prompt templates for the inner loop Builder. For example:
- JDK mismatch → version-focused prompt
- Multi-module → reactor-focused prompt
- Missing plugin → plugin-analysis prompt

## Implementation Relevance
The per-error-class prompt template pattern directly informs how knowledge base entries should be structured — not as generic "patterns" but as error-class-specific Builder instructions with tailored prompts.
