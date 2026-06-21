"""Tests for KB schema — load/save KB entries, all entry types."""

from __future__ import annotations

from pathlib import Path

import pytest

from buildroot.agent.knowledge.schema import (
    EntryType,
    KBEntry,
    TemplateEntry,
    TipEntry,
    TrickEntry,
    load_all_entries,
    load_entry,
    save_entry,
)


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    return tmp_path / "kb"


class TestEntryTypes:
    def test_template_post_init_sets_type(self):
        entry = TemplateEntry(name="t", entry_type=None, description="d")
        assert entry.entry_type == EntryType.TEMPLATE

    def test_tip_post_init_sets_type(self):
        entry = TipEntry(name="t", entry_type=None, description="d")
        assert entry.entry_type == EntryType.TIP

    def test_trick_post_init_sets_type(self):
        entry = TrickEntry(name="t", entry_type=None, description="d")
        assert entry.entry_type == EntryType.TRICK

    def test_template_to_dict_includes_containerfile(self):
        entry = TemplateEntry(
            name="tpl",
            entry_type=None,
            description="a template",
            containerfile="FROM ubuntu",
            coordinate="g:a:1.0",
            l4_score=0.95,
        )
        d = entry.to_dict()
        assert d["type"] == "template"
        assert d["containerfile"] == "FROM ubuntu"
        assert d["coordinate"] == "g:a:1.0"
        assert d["l4_score"] == 0.95

    def test_tip_to_dict_includes_trigger_solution(self):
        entry = TipEntry(
            name="tip1",
            entry_type=None,
            description="a tip",
            trigger="something fails",
            solution="do this",
            caveats="watch out",
        )
        d = entry.to_dict()
        assert d["type"] == "tip"
        assert d["trigger"] == "something fails"
        assert d["solution"] == "do this"
        assert d["caveats"] == "watch out"

    def test_trick_to_dict_includes_error_fix(self):
        entry = TrickEntry(
            name="trick1",
            entry_type=None,
            description="a trick",
            error_pattern="NoSuchMethod",
            fix="add dependency",
            example_log="java.lang.NoSuchMethodError",
        )
        d = entry.to_dict()
        assert d["type"] == "trick"
        assert d["error_pattern"] == "NoSuchMethod"
        assert d["fix"] == "add dependency"


class TestSaveAndLoad:
    def test_save_creates_yaml_file(self, kb_dir: Path):
        entry = TipEntry(name="my-tip", entry_type=None, description="desc")
        path = save_entry(entry, kb_dir)
        assert path.exists()
        assert path.name == "my-tip.yaml"

    def test_roundtrip_tip(self, kb_dir: Path):
        original = TipEntry(
            name="roundtrip-tip",
            entry_type=None,
            description="round trip test",
            tags=["tag1", "tag2"],
            build_systems=["maven"],
            trigger="when X",
            solution="do Y",
            caveats="beware Z",
            times_used=5,
            success_rate=0.8,
        )
        save_entry(original, kb_dir)
        loaded = load_entry(kb_dir / "roundtrip-tip.yaml")
        assert loaded is not None
        assert isinstance(loaded, TipEntry)
        assert loaded.name == "roundtrip-tip"
        assert loaded.trigger == "when X"
        assert loaded.solution == "do Y"
        assert loaded.tags == ["tag1", "tag2"]
        assert loaded.times_used == 5

    def test_roundtrip_template(self, kb_dir: Path):
        original = TemplateEntry(
            name="roundtrip-tpl",
            entry_type=None,
            description="template test",
            containerfile="FROM fedora:39\nRUN dnf install -y java",
            coordinate="org.example:lib:1.0",
            l4_score=0.99,
        )
        save_entry(original, kb_dir)
        loaded = load_entry(kb_dir / "roundtrip-tpl.yaml")
        assert loaded is not None
        assert isinstance(loaded, TemplateEntry)
        assert loaded.containerfile == "FROM fedora:39\nRUN dnf install -y java"
        assert loaded.l4_score == 0.99

    def test_roundtrip_trick(self, kb_dir: Path):
        original = TrickEntry(
            name="roundtrip-trick",
            entry_type=None,
            description="trick test",
            error_pattern="ClassNotFound",
            fix="add jar to classpath",
            example_log="java.lang.ClassNotFoundException: com.foo.Bar",
        )
        save_entry(original, kb_dir)
        loaded = load_entry(kb_dir / "roundtrip-trick.yaml")
        assert loaded is not None
        assert isinstance(loaded, TrickEntry)
        assert loaded.error_pattern == "ClassNotFound"

    def test_load_nonexistent_returns_none(self, kb_dir: Path):
        assert load_entry(kb_dir / "nonexistent.yaml") is None

    def test_load_all_entries_empty_dir(self, kb_dir: Path):
        assert load_all_entries(kb_dir) == []

    def test_load_all_entries_multiple(self, kb_dir: Path):
        save_entry(TipEntry(name="a-tip", entry_type=None, description="d1"), kb_dir)
        save_entry(TrickEntry(name="b-trick", entry_type=None, description="d2"), kb_dir)
        save_entry(TemplateEntry(name="c-tpl", entry_type=None, description="d3"), kb_dir)
        entries = load_all_entries(kb_dir)
        assert len(entries) == 3
        names = {e.name for e in entries}
        assert names == {"a-tip", "b-trick", "c-tpl"}

    def test_save_updates_updated_at(self, kb_dir: Path):
        entry = TipEntry(name="ts-test", entry_type=None, description="d")
        old_ts = entry.updated_at
        save_entry(entry, kb_dir)
        assert entry.updated_at >= old_ts
