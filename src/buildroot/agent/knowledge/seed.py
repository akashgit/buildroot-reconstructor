"""Seed the knowledge base with Bouncy Castle entries."""

from __future__ import annotations

from pathlib import Path

from buildroot.agent.knowledge.schema import (
    TipEntry,
    TrickEntry,
    save_entry,
)


def seed_bouncy_castle_entries(kb_dir: Path) -> int:
    """Seed KB with 10 entries derived from the Bouncy Castle proof-of-concept."""
    entries = [
        TipEntry(
            name="ant-exact-version",
            entry_type=None,  # set by __post_init__
            description="Bouncy Castle requires exact Ant version matching for reproducible builds",
            tags=["ant", "bouncy-castle", "reproducibility", "version-pinning"],
            build_systems=["ant"],
            trigger="Package uses Ant build system and requires reproducible output",
            solution="Pin Ant to the exact version used in the original build (e.g., 1.10.14). "
                     "Download from Apache archives: https://archive.apache.org/dist/ant/binaries/",
            caveats="Different Ant versions produce different JAR metadata and file ordering",
        ),
        TipEntry(
            name="bnd-osgi-wrap",
            entry_type=None,
            description="Use Bnd tool to generate correct OSGI bundle headers in MANIFEST.MF",
            tags=["osgi", "bnd", "manifest", "bouncy-castle", "bundle"],
            build_systems=["ant", "maven", "gradle"],
            trigger="JAR manifest requires OSGI headers (Bundle-SymbolicName, Import-Package, Export-Package)",
            solution="Use Bnd 2.2.0 to wrap the JAR with correct OSGI headers: "
                     "java -jar bnd-2.2.0.jar wrap --output wrapped.jar original.jar "
                     "with a .bnd file specifying Bundle-SymbolicName, Export-Package, Import-Package",
            caveats="Bnd version must match exactly — different versions produce different header formatting. "
                     "Bnd 2.2.0 is the version Bouncy Castle uses historically.",
        ),
        TipEntry(
            name="bnd-before-multirelease",
            entry_type=None,
            description="Bnd wrap must happen BEFORE adding multi-release class files",
            tags=["osgi", "bnd", "multi-release", "ordering", "bouncy-castle"],
            build_systems=["ant"],
            trigger="Package is both an OSGI bundle and a multi-release JAR",
            solution="Build order: (1) compile main classes, (2) create base JAR, "
                     "(3) run Bnd wrap for OSGI headers, (4) compile JDK 9+ classes, "
                     "(5) add multi-release entries with jar --update. "
                     "Reversing steps 3 and 5 corrupts the OSGI headers.",
            caveats="The MANIFEST.MF from Bnd gets Multi-Release: true added later via jar --update",
        ),
        TipEntry(
            name="real-jdk9-binary",
            entry_type=None,
            description="Multi-release JARs need actual JDK 9 for compiling META-INF/versions/9/ classes",
            tags=["multi-release", "jdk9", "bouncy-castle", "bytecode"],
            build_systems=["ant", "maven", "gradle"],
            trigger="JAR contains META-INF/versions/9/ with .class files that must have bytecode major version 53",
            solution="Install real JDK 9 (not JDK 17 with --release 9) for compiling multi-release classes. "
                     "Use adoptopenjdk/openjdk9 Docker image or download from https://jdk.java.net/archive/. "
                     "The --release flag doesn't produce identical bytecode to real JDK 9.",
            caveats="JDK 9 is EOL — find archived binaries. Docker multi-stage builds help: "
                     "stage 1 with JDK 9 compiles the versioned classes, stage 2 with main JDK builds everything else.",
        ),
        TrickEntry(
            name="jdk9-jar-strict",
            entry_type=None,
            description="JDK 9 jar tool is strict about multi-release structure",
            tags=["multi-release", "jdk9", "jar-tool", "bouncy-castle"],
            build_systems=["ant"],
            error_pattern="invalid multi-release jar",
            fix="Use jar --update -f instead of jar cf when adding multi-release entries. "
                "The JDK 9 jar tool validates multi-release structure on creation but not on update. "
                "Alternatively, use JDK 11+ jar tool which is more permissive.",
            example_log="Error: invalid multi-release jar, entry META-INF/versions/9/...",
        ),
        TrickEntry(
            name="encoding-utf8",
            entry_type=None,
            description="Add -encoding UTF-8 to javac for source files with non-ASCII characters",
            tags=["javac", "encoding", "utf8", "bouncy-castle"],
            build_systems=["ant", "maven", "gradle"],
            error_pattern="unmappable character",
            fix="Add -encoding UTF-8 to javac invocations. For Ant: <javac encoding='UTF-8' .../>. "
                "For Maven: <maven.compiler.encoding>UTF-8</maven.compiler.encoding>. "
                "For Gradle: tasks.withType(JavaCompile) { options.encoding = 'UTF-8' }",
            example_log="error: unmappable character (0xC2) for encoding ASCII",
        ),
        TrickEntry(
            name="jar-uf-not-cf",
            entry_type=None,
            description="Use jar uf (update) not jar cf (create) when adding entries to existing JARs",
            tags=["jar-tool", "update", "bouncy-castle"],
            build_systems=["ant", "maven"],
            error_pattern="missing or changed files in JAR",
            fix="When adding multi-release classes or other entries to an existing JAR, "
                "use 'jar uf target.jar -C classes .' instead of creating a new JAR. "
                "jar cf would recreate the archive with different ordering and metadata.",
            example_log="structural mismatch: extra_files or missing_files in comparison report",
        ),
        TipEntry(
            name="signing-irreducible",
            entry_type=None,
            description="Cryptographic signatures in JARs cannot be reproduced — strip or accept the diff",
            tags=["signing", "gpg", "bouncy-castle", "reproducibility"],
            build_systems=["ant", "maven", "gradle"],
            trigger="JAR contains META-INF/*.SF, *.DSA, *.RSA, or *.EC signature files",
            solution="Remove signature files from the rebuilt JAR: "
                     "zip -d rebuilt.jar 'META-INF/*.SF' 'META-INF/*.DSA' 'META-INF/*.RSA' 'META-INF/*.EC'. "
                     "The L4 comparator already ignores signing files in equivalence scoring.",
            caveats="Some packages (especially security libraries like Bouncy Castle) ship signed. "
                     "The signature diff is irreducible without the private key — accept it as a known gap.",
        ),
        TrickEntry(
            name="hsperfdata-suppress",
            entry_type=None,
            description="Suppress JVM hsperfdata files that leak into container builds",
            tags=["jvm", "hsperfdata", "container", "bouncy-castle"],
            build_systems=["ant", "maven", "gradle"],
            error_pattern="hsperfdata",
            fix="Add -XX:-UsePerfData or -XX:+PerfDisableSharedMem to JAVA_OPTS / JAVA_TOOL_OPTIONS "
                "to prevent hsperfdata files from being created during the build. "
                "These files appear in /tmp/hsperfdata_root/ and can accidentally end up in the JAR.",
            example_log="extra_files: ['tmp/hsperfdata_root/...']",
        ),
        TipEntry(
            name="source-date-epoch",
            entry_type=None,
            description="Set SOURCE_DATE_EPOCH=0 for reproducible timestamps in all build tools",
            tags=["reproducibility", "timestamps", "epoch", "bouncy-castle"],
            build_systems=["ant", "maven", "gradle"],
            trigger="JAR file timestamps differ between original and rebuilt versions",
            solution="Set ENV SOURCE_DATE_EPOCH=0 in the Containerfile. This zeroes out timestamps in "
                     "ZIP entries, tar archives, and build tool outputs. For Maven, also add "
                     "-Dproject.build.outputTimestamp=2000-01-01T00:00:00Z",
            caveats="Some tools ignore SOURCE_DATE_EPOCH — verify with jar -tvf that timestamps are zeroed",
        ),
    ]

    count = 0
    for entry in entries:
        save_entry(entry, kb_dir)
        count += 1

    return count
