---
tags:
  - factory
  - source
source: factory-archivist
date: 2026-06-07
---

# Macaron BuildGen (Oracle Labs)

**Closest existing tool** to Buildroot Reconstructor.

## Key Findings

- Supply-chain security analysis framework from Oracle Labs
- BuildGen extension automates generation of build specifications for Maven artifacts
- Analyzes CI workflows (GitHub Actions) to detect `setup-java`, build commands, GPG signing
- Extracts JDK version, build tool version, and build commands
- Assigns confidence scores to detected build commands
- Outputs Reproducible Central buildspec format (shell-oriented, not Containerfile)
- Paper: "Unlocking Reproducibility: Automating re-Build Process for Open-Source Software" (ASE 2025)
- BuildGen under review for merge into Macaron; Commit Finder shipped in v0.16.0

## Gap vs. Our Tool

BuildGen produces buildspecs (shell-oriented), not Containerfiles. Our differentiator is executable environment specification (Containerfile) rather than metadata.

## Reference

- Repository: https://github.com/oracle/macaron
- Paper: https://arxiv.org/html/2509.08204v1
