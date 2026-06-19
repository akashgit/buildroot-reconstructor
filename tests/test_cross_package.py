"""Tests for cross-package knowledge transfer via RecipeStore.get_group_hints()."""

import json
import pytest
from pathlib import Path

from buildroot.agent.models import RecipeStore


@pytest.fixture
def recipe_dir(tmp_path):
    return tmp_path / "recipes"


@pytest.fixture
def store(recipe_dir):
    return RecipeStore(recipe_dir=recipe_dir)


def _save_recipe(recipe_dir, coordinate, levels):
    recipe_dir.mkdir(parents=True, exist_ok=True)
    safe = coordinate.replace(":", "_").replace(".", "_")
    path = recipe_dir / f"{safe}.json"
    path.write_text(json.dumps({"coordinate": coordinate, "levels": levels}) + "\n")


class TestGetGroupHints:
    def test_no_recipes_returns_empty(self, store):
        hints = store.get_group_hints("org.example:foo:1.0")
        assert hints == []

    def test_same_group_returns_hints(self, store, recipe_dir):
        _save_recipe(recipe_dir, "org.example:bar:2.0", {
            "l3": {"containerfile": "FROM jdk:17", "reward": 0.50},
            "l4": {"containerfile": "FROM jdk:17\nRUN mvn", "reward": 0.99},
        })
        hints = store.get_group_hints("org.example:foo:1.0")
        assert len(hints) == 1
        assert hints[0]["coordinate"] == "org.example:bar:2.0"
        assert hints[0]["reward"] == 0.99
        assert "containerfile" in hints[0]

    def test_different_group_excluded(self, store, recipe_dir):
        _save_recipe(recipe_dir, "com.other:bar:2.0", {
            "l4": {"containerfile": "FROM jdk:11", "reward": 0.99},
        })
        hints = store.get_group_hints("org.example:foo:1.0")
        assert hints == []

    def test_self_excluded(self, store, recipe_dir):
        _save_recipe(recipe_dir, "org.example:foo:1.0", {
            "l4": {"containerfile": "FROM jdk:17", "reward": 0.99},
        })
        hints = store.get_group_hints("org.example:foo:1.0")
        assert hints == []

    def test_multiple_same_group(self, store, recipe_dir):
        _save_recipe(recipe_dir, "org.example:bar:2.0", {
            "l4": {"containerfile": "CF1", "reward": 0.99},
        })
        _save_recipe(recipe_dir, "org.example:baz:3.0", {
            "l3": {"containerfile": "CF2", "reward": 0.55},
        })
        hints = store.get_group_hints("org.example:foo:1.0")
        assert len(hints) == 2
        coords = {h["coordinate"] for h in hints}
        assert coords == {"org.example:bar:2.0", "org.example:baz:3.0"}

    def test_returns_best_level(self, store, recipe_dir):
        _save_recipe(recipe_dir, "org.example:bar:2.0", {
            "l2": {"containerfile": "CF-L2", "reward": 0.15},
            "l3": {"containerfile": "CF-L3", "reward": 0.50},
        })
        hints = store.get_group_hints("org.example:foo:1.0")
        assert len(hints) == 1
        assert hints[0]["reward"] == 0.50
        assert hints[0]["containerfile"] == "CF-L3"

    def test_corrupt_json_skipped(self, store, recipe_dir):
        recipe_dir.mkdir(parents=True, exist_ok=True)
        (recipe_dir / "bad.json").write_text("not json!")
        _save_recipe(recipe_dir, "org.example:bar:2.0", {
            "l4": {"containerfile": "CF", "reward": 0.99},
        })
        hints = store.get_group_hints("org.example:foo:1.0")
        assert len(hints) == 1

    def test_empty_dir(self, store, recipe_dir):
        recipe_dir.mkdir(parents=True, exist_ok=True)
        hints = store.get_group_hints("org.example:foo:1.0")
        assert hints == []

    def test_hints_from_save_api(self, store):
        store.save("org.example:bar:2.0", 3, "FROM jdk:17", 0.55)
        hints = store.get_group_hints("org.example:foo:1.0")
        assert len(hints) == 1
        assert hints[0]["coordinate"] == "org.example:bar:2.0"
