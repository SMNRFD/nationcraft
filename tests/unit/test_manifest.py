"""Unit tests for the plugin manifest parser."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nationcraft.core.plugins import PluginManifest


def test_manifest_parses(tmp_path: Path) -> None:
    data = {
        "id": "demo",
        "name": "Demo Plugin",
        "version": "1.0.0",
        "author": "Tester",
        "entrypoint": "plugin.py",
    }
    p = tmp_path / "plugin.json"
    p.write_text(json.dumps(data))
    m = PluginManifest.from_path(p)
    assert m.id == "demo"
    assert m.version == "1.0.0"
    assert m.api_version == "1.0"


def test_manifest_rejects_bad_id() -> None:
    with pytest.raises(Exception):
        PluginManifest(id="Bad-ID", name="X", version="1.0.0")


def test_manifest_rejects_bad_version() -> None:
    with pytest.raises(Exception):
        PluginManifest(id="ok", name="X", version="v1")
