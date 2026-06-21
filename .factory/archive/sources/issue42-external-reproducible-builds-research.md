---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-42
  - reproducible-builds
source: factory-archivist
date: 2026-06-18
research_type: external
---

# Issue #42 External Research: Structured Template Modification & Reproducible Java Builds

## Summary

External research covering Jinja2 template patterns, Java reproducibility taxonomy, container reproducibility, and L4 divergence classification. Directly informs the spec_overrides vocabulary expansion.

## Key Findings

### Jinja2 Template Architecture — Flat Conditionals Are Correct
- Template inheritance (`{% block %}`) is overkill for this project — all variation driven by BuildrootSpec fields
- Current flat-template-with-conditionals approach is the right pattern
- `default()` filter recommended for optional variables: `{{ extra_maven_args | default('') }}`
- Security: No SSTI risk since templates are project-controlled, not user-provided
- Prior art: jocker, Dockerfile_generator, DockerMake all use similar flat-template patterns

### Java Reproducibility Taxonomy (Sharma et al., 2025)
From "Causes and Canonicalization of Unreproducible Builds in Java" (12,803 artifacts studied):

| Root Cause | Mitigation | Project Status |
|-----------|-----------|---------------|
| Build manifests (MANIFEST.MF) | Strip Built-By, Build-Jdk, Created-By, Bnd-LastModified | Already implemented |
| SBOM variations (CycloneDX) | Strip bom.xml/bom.json | NOT handled |
| Filesystem (permissions, ordering) | Normalize ZIP metadata, SOURCE_DATE_EPOCH=0 | Partially handled |
| JVM bytecode (debug info, lambda naming) | Match JDK major version exactly; jNorm/SootDiff for canonicalization | jdk_version override exists |
| Versioning properties (git.properties) | Strip git.properties before comparison | NOT handled |
| Timestamps (10+ locations) | project.build.outputTimestamp + SOURCE_DATE_EPOCH | Implemented in exp 13 |

### Canonicalization Success Rates
- OSS-Rebuild (Google): 9.41% (archive metadata only)
- Chains-Rebuild: 26.60% (archive + MANIFEST.MF + pom.properties + git.properties)
- jNorm (bytecode): 29.7% (JVM bytecode canonicalization)
- Combined: ~27% of unreproducible artifacts become reproducible

### Maven/Gradle Reproducibility Configuration
- Maven: `project.build.outputTimestamp` + `SOURCE_DATE_EPOCH` (both already in templates)
- Maven 4.0.0-beta-5+: Reproducible mode active by default
- Gradle: `preserveFileTimestamps=false`, `reproducibleFileOrder=true`, `dirPermissions/filePermissions`
- Locale pinning: `-Dfile.encoding=UTF-8 -Duser.language=en -Duser.country=US` (missing from templates)

### Container Reproducibility
- Buildah v1.41/Podman 5.6+: `--source-date-epoch=0 --rewrite-timestamp` for layer-level determinism
- Red Hat Project Hummingbird: SOURCE_DATE_EPOCH from Git commit timestamp (vs our epoch-zero approach)
- Base image pinning: Should use digest (`@sha256:...`) not floating tags — `jdk_minor_version` override addresses this partially

### L4 Divergence → spec_overrides Mapping
| Divergence | Detection | Override |
|-----------|----------|---------|
| Timestamp in MANIFEST.MF | Bnd-LastModified present | Already stripped |
| JDK version in MANIFEST.MF | Build-Jdk differs | `jdk_version` |
| File ordering | Same entries, different CRC | `extra_maven_args: "-T1"` |
| git.properties divergence | Resource mismatch | `post_build_cmds: ["find ... -delete"]` |
| Bytecode: JDK major mismatch | API differences | `jdk_version` to match original |
| SBOM divergence | CycloneDX serial/timestamp | `post_build_cmds: ["find ... bom.* -delete"]` |

### Additional spec_overrides Identified
- `post_build_cmds`, `extra_maven_args`, `extra_gradle_args`, `workdir_subdir`
- `env_vars`, `maven_settings`, `jdk_minor_version`, `source_date_epoch`
- `strip_sbom`, `strip_git_props`, `locale_pin`, `disable_parallel`

## References
- Sharma et al. 2025: arxiv.org/html/2504.21679v4
- Apache Maven Reproducible Builds Guide
- Chains-Rebuild: github.com/chains-project/chains-e-e
- SootDiff: ACM DL doi.org/10.1145/3315568.3329966
- Reproducible Central: github.com/jvm-repo-rebuild/reproducible-central
- Buildah v1.41: buildah.io/releases/2025/07/21
- Red Hat Project Hummingbird: developers.redhat.com/articles/2026/03/26
