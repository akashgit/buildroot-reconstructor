---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level4
source: factory-archivist
date: 2026-06-09
---

# Reproducible Builds Ecosystem — Standard Approach

Reproducible Central (https://github.com/jvm-repo-rebuild/reproducible-central) is the definitive reference for Maven artifact reproducibility verification. Their 3+ years of experience provides the gold-standard methodology.

## Their Approach
1. **`.buildspec` files** define: groupId/artifactId/version, gitRepo, gitTag, JDK version, Maven version, build command, newline style, timezone, locale
2. **`rebuild.sh`** executes the build in Docker using the buildspec
3. **`.buildinfo` file** records output checksums (SHA-512 per artifact)
4. **`.buildcompare` file** stores comparison results — `ko` attribute indicates non-reproducible entries
5. **`build_diffoscope.sh`** runs diffoscope on mismatched artifacts

## Key Findings
- **Timestamps** are the #1 source of non-reproducibility in JARs
- Compare `Build-Jdk-Spec` (major version only), not `Build-Jdk` — the latter includes minor versions
- **`project.build.outputTimestamp`** in POM is the Maven mechanism for reproducible builds
- Only **major JDK version** matters for reproducibility in most cases
- `.buildspec` format proved more practical than `.buildinfo` for actual verification

## maven-artifact-plugin:compare
- Official Maven tool for reproducibility verification
- Generates `.buildinfo` from current build, downloads reference from Central
- Reports per-artifact match/mismatch with copy-pasteable diffoscope commands
- Extracts `Build-Jdk-Spec` from MANIFEST.MF and OS from `pom.properties` newlines

## Relevance to Level 4
Our `buildroot.json` sidecar was designed for interoperability with this `.buildspec` format. The comparison methodology validates our layered approach — they also go structural → metadata → bytecode → diffoscope.

## References
- [Reproducible Central](https://github.com/jvm-repo-rebuild/reproducible-central)
- [BUILDSPEC.md format](https://github.com/jvm-repo-rebuild/reproducible-central/blob/master/doc/BUILDSPEC.md)
- [build_diffoscope.sh](https://github.com/jvm-repo-rebuild/reproducible-central/blob/master/build_diffoscope.sh)
- [Maven Reproducible Builds Guide](https://maven.apache.org/guides/mini/guide-reproducible-builds.html)
- [maven-artifact-plugin:compare](https://maven.apache.org/plugins/maven-artifact-plugin/reproducible.html)
