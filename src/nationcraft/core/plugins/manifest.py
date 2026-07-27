"""Plugin manifest model (``plugin.json``)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PluginDependency(BaseModel):
    """Declares a dependency on another plugin or python package."""

    name: str
    version: str | None = None
    optional: bool = False


class PluginManifest(BaseModel):
    """The ``plugin.json`` schema.

    Each plugin must ship a ``plugin.json`` next to its entrypoint.
    """

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$",
                    description="Unique plugin id (snake_case)")
    name: str
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+")
    api_version: str = Field(default="1.0")
    author: str = ""
    description: str = ""
    homepage: str = ""
    license: str = "AGPL-3.0-or-later"
    entrypoint: str = "plugin.py"
    module: str | None = Field(default=None,
                               description="Dotted module path to import (defaults to '<id>.plugin')")
    permissions: list[str] = Field(default_factory=list)
    dependencies: list[PluginDependency] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    load_order: int = 100
    enabled_by_default: bool = True

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("plugin id must be alphanumeric+underscore")
        return v

    @classmethod
    def from_path(cls, path: Path) -> "PluginManifest":
        import json
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return cls(**data)
