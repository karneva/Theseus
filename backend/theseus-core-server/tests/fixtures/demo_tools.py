"""테스트 전용 데모 도구.

예전에는 ALL_CORE_TOOLS 맨 앞에 등록되어 운영 LLM에도 노출됐습니다(dummy_echo는
모든 사용자에게, system_reboot는 레벨 5 사용자에게 가짜 "재부팅" 결과를 반환).
도구 파이프라인과 RBAC 테스트에서만 쓰도록 이 fixture로 옮겼습니다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from theseus_engine.tools.core.base_tools import BaseTool, ToolExecutionContext, ToolResult


class DummyInput(BaseModel):
    """Input for the dummy_echo tool."""

    message: str = Field(description="The message to echo back.")


class DummyTool(BaseTool):
    """입력 메시지를 그대로 돌려주는 연결 테스트용 도구."""

    name = "dummy_echo"
    description = "Echoes back the provided message to verify tool execution pipeline."
    input_model = DummyInput

    async def execute(self, arguments: DummyInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"Echo: {arguments.message}")


class SystemRebootInput(BaseModel):
    """Input for the system_reboot tool."""

    reason: str = Field(description="Reason for the reboot.")


class SystemRebootTool(BaseTool):
    """높은 권한 레벨(5) RBAC 테스트용 mock 도구. 실제로는 아무 것도 하지 않습니다."""

    name = "system_reboot"
    description = "Simulates a system reboot for testing high-privilege RBAC tools."
    input_model = SystemRebootInput
    permission_level = 5

    async def execute(
        self, arguments: SystemRebootInput, context: ToolExecutionContext
    ) -> ToolResult:
        return ToolResult(output=f"System reboot initiated. Reason: {arguments.reason}")
