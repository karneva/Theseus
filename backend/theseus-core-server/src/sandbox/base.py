from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class SandboxUnavailableError(RuntimeError):
    """Raised when the sandbox backend cannot be reached safely."""


# sandbox 컨테이너 실행 시간 상한(초). 긴 실행은 sandbox 자원을 오래 점유하고
# 무한 루프 Tool이 worker를 묶어 두므로 1~60초로 제한합니다.
SANDBOX_MIN_TIMEOUT_SECONDS = 1
SANDBOX_MAX_TIMEOUT_SECONDS = 60


class SandboxInput(BaseModel):
    project_id: int | str
    tool_name: str
    tool_code: str
    payload: Dict[str, Any]
    timeout_seconds: int = Field(
        10, ge=SANDBOX_MIN_TIMEOUT_SECONDS, le=SANDBOX_MAX_TIMEOUT_SECONDS
    )
    runner_script_path: Optional[str] = None


class SandboxExecutionRequest(BaseModel):
    tool_name: str
    tool_code: str
    payload: Dict[str, Any]
    timeout_seconds: int = Field(
        10, ge=SANDBOX_MIN_TIMEOUT_SECONDS, le=SANDBOX_MAX_TIMEOUT_SECONDS
    )


class SandboxOutput(BaseModel):
    success: bool
    result: Optional[Dict[str, Any]] = None
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    exit_code: Optional[int] = None
    timed_out: bool = False
    resource_limited: bool = False
    execution_time_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolRunner(ABC):
    @abstractmethod
    async def execute(self, request: SandboxInput) -> SandboxOutput:
        """
        주어진 툴 코드를 격리된 환경에서 실행하고 결과를 반환합니다.
        """
        pass
