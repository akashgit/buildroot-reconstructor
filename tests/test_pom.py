"""Tests for POM parsing and parent chain resolution."""

from __future__ import annotations

import pytest

from buildroot.parsers.pom import PomParser
from buildroot.utils.maven_central import fetch_pom

SIMPLE_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>my-app</artifactId>
    <version>1.2.3</version>
    <packaging>jar</packaging>

    <properties>
        <java.version>17</java.version>
        <spring.version>5.3.18</spring.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework</groupId>
            <artifactId>spring-core</artifactId>
            <version>${spring.version}</version>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.11.0</version>
                <configuration>
                    <release>17</release>
                </configuration>
            </plugin>
        </plugins>
    </build>

    <profiles>
        <profile>
            <id>ci</id>
            <properties>
                <skip.tests>true</skip.tests>
            </properties>
        </profile>
    </profiles>

    <modules>
        <module>core</module>
        <module>web</module>
    </modules>
</project>
"""

PARENT_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>parent</artifactId>
    <version>1.0.0</version>
    <packaging>pom</packaging>

    <properties>
        <base.prop>from-parent</base.prop>
        <override.me>parent-value</override.me>
    </properties>

    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>org.apache.commons</groupId>
                <artifactId>commons-lang3</artifactId>
                <version>3.12.0</version>
            </dependency>
        </dependencies>
    </dependencyManagement>
</project>
"""

CHILD_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>com.example</groupId>
        <artifactId>parent</artifactId>
        <version>1.0.0</version>
    </parent>

    <artifactId>child</artifactId>

    <properties>
        <override.me>child-value</override.me>
        <child.only>yes</child.only>
    </properties>
</project>
"""

GRANDPARENT_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>grandparent</artifactId>
    <version>0.1.0</version>
    <packaging>pom</packaging>

    <properties>
        <gp.prop>from-grandparent</gp.prop>
        <base.prop>from-grandparent-overridden</base.prop>
    </properties>
</project>
"""

PARENT_WITH_GRANDPARENT = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>com.example</groupId>
        <artifactId>grandparent</artifactId>
        <version>0.1.0</version>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>parent</artifactId>
    <version>1.0.0</version>
    <packaging>pom</packaging>

    <properties>
        <base.prop>from-parent</base.prop>
        <override.me>parent-value</override.me>
    </properties>
</project>
"""

CHILD_WITH_THREE_LEVELS = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>com.example</groupId>
        <artifactId>parent</artifactId>
        <version>1.0.0</version>
    </parent>

    <artifactId>child</artifactId>

    <properties>
        <override.me>child-value</override.me>
        <child.only>yes</child.only>
    </properties>
</project>
"""


class TestParseSimplePom:
    def test_extracts_coordinates(self):
        parser = PomParser()
        pom = parser.parse(SIMPLE_POM)
        assert pom.group_id == "com.example"
        assert pom.artifact_id == "my-app"
        assert pom.version == "1.2.3"
        assert pom.packaging == "jar"

    def test_extracts_properties(self):
        parser = PomParser()
        pom = parser.parse(SIMPLE_POM)
        assert pom.properties["java.version"] == "17"
        assert pom.properties["spring.version"] == "5.3.18"

    def test_extracts_dependencies(self):
        parser = PomParser()
        pom = parser.parse(SIMPLE_POM)
        assert len(pom.dependencies) == 1
        dep = pom.dependencies[0]
        assert dep["groupId"] == "org.springframework"
        assert dep["artifactId"] == "spring-core"
        assert dep["version"] == "${spring.version}"

    def test_extracts_build_plugins(self):
        parser = PomParser()
        pom = parser.parse(SIMPLE_POM)
        assert len(pom.build_plugins) == 1
        plugin = pom.build_plugins[0]
        assert plugin["artifactId"] == "maven-compiler-plugin"
        assert plugin["configuration"]["release"] == "17"

    def test_extracts_profiles(self):
        parser = PomParser()
        pom = parser.parse(SIMPLE_POM)
        assert len(pom.profiles) == 1
        assert pom.profiles[0]["id"] == "ci"

    def test_extracts_modules(self):
        parser = PomParser()
        pom = parser.parse(SIMPLE_POM)
        assert pom.modules == ["core", "web"]

    def test_inherits_group_id_from_parent(self):
        parser = PomParser()
        pom = parser.parse(CHILD_POM)
        assert pom.group_id == "com.example"
        assert pom.artifact_id == "child"
        assert pom.version == "1.0.0"


class TestParentChainResolution:
    def test_three_level_chain(self, monkeypatch):
        """Test a 3-level chain: child -> parent -> grandparent."""
        fetch_map = {
            "com.example:parent:1.0.0": PARENT_WITH_GRANDPARENT,
            "com.example:grandparent:0.1.0": GRANDPARENT_POM,
        }

        def mock_fetch(gid, aid, ver, *, no_cache=False, cache_dir=None):
            key = f"{gid}:{aid}:{ver}"
            if key in fetch_map:
                return fetch_map[key]
            raise Exception(f"Not found: {key}")

        monkeypatch.setattr("buildroot.parsers.pom.fetch_pom", mock_fetch)

        parser = PomParser()
        child = parser.parse(CHILD_WITH_THREE_LEVELS)
        chain = parser.resolve_parent_chain(child)

        assert len(chain) == 3
        assert chain[0].artifact_id == "child"
        assert chain[1].artifact_id == "parent"
        assert chain[2].artifact_id == "grandparent"

    def test_merge_three_level_chain(self, monkeypatch):
        """Child properties override parent, which override grandparent."""
        fetch_map = {
            "com.example:parent:1.0.0": PARENT_WITH_GRANDPARENT,
            "com.example:grandparent:0.1.0": GRANDPARENT_POM,
        }

        def mock_fetch(gid, aid, ver, *, no_cache=False, cache_dir=None):
            key = f"{gid}:{aid}:{ver}"
            if key in fetch_map:
                return fetch_map[key]
            raise Exception(f"Not found: {key}")

        monkeypatch.setattr("buildroot.parsers.pom.fetch_pom", mock_fetch)

        parser = PomParser()
        child = parser.parse(CHILD_WITH_THREE_LEVELS)
        chain = parser.resolve_parent_chain(child)
        merged = parser.merge_poms(chain)

        assert merged.properties["override.me"] == "child-value"
        assert merged.properties["base.prop"] == "from-parent"
        assert merged.properties["gp.prop"] == "from-grandparent"
        assert merged.properties["child.only"] == "yes"


class TestCycleDetection:
    def test_cycle_raises(self, monkeypatch):
        """A -> B -> A should raise ValueError."""
        pom_a = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>com.example</groupId>
        <artifactId>b</artifactId>
        <version>1.0</version>
    </parent>
    <groupId>com.example</groupId>
    <artifactId>a</artifactId>
    <version>1.0</version>
</project>
"""
        pom_b = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>com.example</groupId>
        <artifactId>a</artifactId>
        <version>1.0</version>
    </parent>
    <groupId>com.example</groupId>
    <artifactId>b</artifactId>
    <version>1.0</version>
</project>
"""

        def mock_fetch(gid, aid, ver, *, no_cache=False, cache_dir=None):
            if aid == "b":
                return pom_b
            raise Exception("Not found")

        monkeypatch.setattr("buildroot.parsers.pom.fetch_pom", mock_fetch)

        parser = PomParser()
        a = parser.parse(pom_a)

        with pytest.raises(ValueError, match="Cycle detected"):
            parser.resolve_parent_chain(a)


class TestFetchSpringBootPom:
    @pytest.mark.integration
    def test_fetch_and_parse_spring_boot(self):
        """Integration: fetch spring-boot 2.7.18 and parse its flat POM."""
        parser = PomParser()

        xml_text = fetch_pom(
            "org.springframework.boot", "spring-boot", "2.7.18"
        )
        pom = parser.parse(xml_text)

        assert pom.group_id == "org.springframework.boot"
        assert pom.artifact_id == "spring-boot"
        assert pom.version == "2.7.18"
        assert len(pom.dependencies) > 0

    @pytest.mark.integration
    def test_fetch_and_resolve_starter_parent_chain(self):
        """Integration: resolve spring-boot-starter-parent parent chain."""
        parser = PomParser()

        xml_text = fetch_pom(
            "org.springframework.boot", "spring-boot-starter-parent", "2.7.18"
        )
        pom = parser.parse(xml_text)

        assert pom.artifact_id == "spring-boot-starter-parent"

        chain = parser.resolve_parent_chain(pom)
        assert len(chain) >= 2

        artifact_ids = [p.artifact_id for p in chain]
        assert "spring-boot-starter-parent" in artifact_ids
        assert "spring-boot-dependencies" in artifact_ids

        merged = parser.merge_poms(chain)
        assert merged.artifact_id == "spring-boot-starter-parent"
        assert len(merged.properties) > 0
        assert "java.version" in merged.properties
