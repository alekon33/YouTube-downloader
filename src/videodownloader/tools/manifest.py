"""Validated external-tool manifest models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolAsset:
    """One pinned downloadable artifact."""

    name: str
    version: str
    url: str
    sha256: str
    architecture: str
    archive: bool


@dataclass(frozen=True, slots=True)
class ToolManifest:
    """Versioned collection of trusted tool artifacts."""

    schema_version: int
    tools: dict[str, ToolAsset]

    @classmethod
    def packaged(cls) -> ToolManifest:
        resource = files("videodownloader.resources").joinpath("tools-manifest.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ToolManifest:
        schema_version = int(payload.get("schema_version", 0))
        if schema_version != 1:
            raise ValueError(f"Unsupported tool manifest schema: {schema_version}")
        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, dict):
            raise ValueError("Tool manifest does not contain a tools mapping.")
        tools: dict[str, ToolAsset] = {}
        for name, raw in raw_tools.items():
            if not isinstance(name, str) or not isinstance(raw, dict):
                raise ValueError("Invalid tool manifest entry.")
            asset = ToolAsset(
                name=name,
                version=str(raw["version"]),
                url=str(raw["url"]),
                sha256=str(raw["sha256"]).lower(),
                architecture=str(raw["architecture"]),
                archive=bool(raw["archive"]),
            )
            if len(asset.sha256) != 64 or any(c not in "0123456789abcdef" for c in asset.sha256):
                raise ValueError(f"Invalid SHA-256 for {name}.")
            if not asset.url.startswith("https://"):
                raise ValueError(f"Insecure download URL for {name}.")
            tools[name] = asset
        return cls(schema_version=schema_version, tools=tools)

