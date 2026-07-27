"""Tests for the plugin loader."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from nationcraft.core.plugins import PluginLoader, PluginRegistry, PluginState


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    p = tmp_path / "demo"
    p.mkdir()
    (p / "plugin.json").write_text(json.dumps({
        "id": "demo",
        "name": "Demo Plugin",
        "version": "1.0.0",
        "author": "Tests",
        "entrypoint": "plugin.py",
    }))
    (p / "plugin.py").write_text(textwrap.dedent("""
        from nationcraft.core.config import ResourceDef

        def register(ctx):
            ctx.api.register_resource(ResourceDef(
                key='plasma', name='Plasma', icon='🔵', base_price=1000.0
            ))
    """))
    return tmp_path


def test_plugin_discovery(plugin_dir: Path) -> None:
    # Reset singleton
    PluginRegistry._instance = None
    loader = PluginLoader([plugin_dir])
    n = loader.discover()
    assert n == 1
    rec = PluginRegistry.instance().get("demo")
    assert rec is not None
    assert rec.manifest.id == "demo"


def test_plugin_load_registers_resource(plugin_dir: Path) -> None:
    PluginRegistry._instance = None
    from nationcraft.core.config import game_data
    game_data._resources = {}  # reset
    loader = PluginLoader([plugin_dir])
    loader.discover()
    loader.load_all()
    assert "plasma" in game_data.resources
    assert game_data.resources["plasma"].base_price == 1000.0
    rec = PluginRegistry.instance().get("demo")
    assert rec.state == PluginState.ENABLED
