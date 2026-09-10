from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ToolCreationError(RuntimeError):
    """서버의 Tool 생성 파이프라인이 다음 단계로 진행할 수 없을 때 발생합니다."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.errors = errors or []


@dataclass(slots=True)
class ServerToolCreationRequest:
    tool_name: str
    python_code: str
    permission_level: int
    project_id: str
    creator_user_id: str
    chat_session_id: int
    plan_id: str
    run_id: str | None = None


@dataclass(slots=True)
class ServerToolArtifactPaths:
    project_dir: Path
    module_path: Path
    metadata_path: Path
    module_name: str


@dataclass(slots=True)
class ServerToolCreationResult:
    status: str
    stage: str
    tool_name: str
    message: str
    module_path: str | None = None
    metadata_path: str | None = None
    permission_level: int | None = None
    registry_registered: bool = False
    errors: list[str] = field(default_factory=list)
    trace_id: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ServerToolSourceResult:
    status: str
    stage: str
    tool_name: str
    message: str
    project_id: str
    module_name: str
    module_path: str
    metadata_path: str
    host_module_path: str | None = None
    host_metadata_path: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    permission_level: int | None = None
    registry_registered: bool = False
    sandbox_verified: bool = False
    errors: list[str] = field(default_factory=list)
    trace_id: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("source", None)
        return payload
