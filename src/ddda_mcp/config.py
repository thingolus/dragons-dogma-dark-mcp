"""Explicit local configuration; importing this module has no side effects."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import ToolFailure, contained, read_json

BASELINE = "61ed1bf830141b75981babe362cef42579eb98e3"
GAME_SHA256 = "19facc2642f79a09d14ce55eace5f228161f2f8bab60ec67eb3c6196cc6277b8"


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_inline_result_bytes: int = Field(16384, ge=2048, le=65536)
    max_page_items: int = Field(100, ge=1, le=100)
    read_timeout_seconds: int = Field(10, ge=1, le=30)
    max_experiment_seconds: int = Field(120, ge=1, le=120)
    max_trace_bytes: int = Field(10485760, ge=8192, le=10485760)
    max_live_operations: Literal[1] = 1


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    game_root: str = ".."
    coop_source_root: str = "../ddda-local-coop"
    coop_source_commit: str = Field(BASELINE, pattern=r"^[0-9a-f]{40}$")
    expected_game_sha256: str = Field(GAME_SHA256, pattern=r"^[0-9a-f]{64}$")
    artifact_root: str = "private/runs"
    index_root: str = "cache"
    transport: Literal["stdio"] = "stdio"
    profile: Literal["read_only", "development"] = "read_only"
    limits: Limits = Field(default_factory=Limits)
    cmake: str | None = None
    ghidra_home: str | None = None
    java: str | None = None
    ghidra_project_dir: str | None = None
    ghidra_project_name: str = Field("DDDA", pattern=r"^[A-Za-z0-9_-]+$")
    # Named directories are selected in trusted local config, never supplied as tool paths.
    deployment_candidates: dict[str, str] = Field(default_factory=dict)
    save_roots: list[str] = Field(default_factory=list)


class Config:
    def __init__(self, root: Path, settings: Settings):
        self.root = root.resolve()
        self.settings = settings
        self.game = (self.root / settings.game_root).resolve()
        self.source = (self.root / settings.coop_source_root).resolve()
        self.artifacts = contained(self.root, self.root / settings.artifact_root)
        self.cache = contained(self.root, self.root / settings.index_root)
        if self.artifacts == self.root or self.cache == self.root:
            raise ToolFailure("invalid_config", "Generated state must use dedicated subdirectories.")

    @classmethod
    def load(cls, root: Path, config_path: Path | None = None) -> "Config":
        path = config_path or root / "config/local.json"
        if config_path is not None and not path.is_file():
            raise ToolFailure("invalid_config", "The explicitly selected configuration file is missing.")
        return cls(root, Settings.model_validate(read_json(path) if path.is_file() else {}))

    def require_development(self) -> None:
        if self.settings.profile != "development":
            raise ToolFailure(
                "profile_disabled", "This operation requires profile=development in local config."
            )
