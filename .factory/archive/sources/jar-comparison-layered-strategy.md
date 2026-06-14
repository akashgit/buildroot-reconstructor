---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level4
source: factory-archivist
date: 2026-06-09
---

# JAR Comparison Techniques — Four-Layer Strategy

Level 4 artifact comparison requires a layered approach because byte-for-byte JAR comparison will always fail due to well-documented non-deterministic elements in Java builds.

## Layer 1: Structural (ZIP entry listing)
- Use Python `zipfile.ZipFile` to list entries in both JARs
- Compare entry names, counts, uncompressed sizes, and CRC-32 values
- Catches major divergence: wrong branch, wrong module, missing dependencies
- Cheapest layer — run first as a gate

## Layer 2: Metadata (MANIFEST.MF + resources)
- Parse MANIFEST.MF, strip non-deterministic keys: `Build-Jdk`, `Built-By`, `Created-By`, `Build-Timestamp`, `Bnd-LastModified`
- Byte-compare resource files (`.properties` with timestamp comments stripped, `.xml`, `META-INF/services/*`)
- Check `pom.properties` and `pom.xml` inside `META-INF/maven/` — version and groupId must match

## Layer 3: Bytecode (CFR decompiler preferred)
- **CFR** produces stable Java source with symbolic references — immediately diffable
- **javap -c** output depends on constant pool indices, producing enormous false-positive diffs (1100+ lines from a 2-char source change)
- CFR is a single zero-dependency JAR, handles Java 6 through 14+
- Usage: decompile both JARs to temp directories and `diff -r`

## Layer 4: diffoscope (deep recursive comparison)
- Gold standard from Reproducible Builds project — recursively unpacks JARs, decompiles `.class` files
- v317 (April 2026), has specific Java `.class` file support
- Known limitation: when archive contents are identical but compression levels differ, falls back to unhelpful binary diff — extract first as workaround
- Use as optional deep investigation when Layers 1-3 find differences

## Recommendation
Implement Layers 1-3 in Python (stdlib + CFR) for the core comparison pipeline. Use diffoscope as optional Layer 4 for investigation. Python's `zipfile` is already imported in `maven_central.py`.

## References
- [CFR decompiler](https://www.benf.org/other/cfr/)
- [diffoscope](https://diffoscope.org/)
- [diffoscope Java class fix v303](https://salsa.debian.org/reproducible-builds/diffoscope/-/commit/9ec7aad2)
