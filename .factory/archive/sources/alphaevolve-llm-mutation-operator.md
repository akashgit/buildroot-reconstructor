---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - outer-loop
source: factory-archivist
date: 2026-06-13
---

# AlphaEvolve: LLM as Mutation Operator (Google DeepMind)

**Source**: [AlphaEvolve: A Gemini-powered coding agent for designing advanced algorithms](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)

## Key Findings for Outer Loop

### LLM Ensemble as Mutation Operators
Uses an ensemble of LLMs (Flash for throughput, Pro for quality) as mutation operators within an evolutionary loop. The program database uses MAP-elites island model.

### SEARCH/REPLACE Diff Format
Code changes are expressed as SEARCH/REPLACE diffs — targeted diffs rather than full file rewrites to minimize blast radius. Good output contract for the code-change LLM.

### MAP-Elites Population Management
Maintains diverse solutions across behavioral dimensions. Relevant to strategy archive: maintain diverse strategies rather than converging on a single approach.

## Implementation Relevance
Our outer loop Builder should generate targeted diffs (not full file rewrites) to minimize blast radius. However, our mutable files (builder.py=190 lines, analyzer.py=200 lines, loop.py=180 lines) are small enough that full-file rewrite is acceptable for v1 — validated by git diff against the original. The ensemble pattern is less relevant since we target one model (claude-opus-4-6).
