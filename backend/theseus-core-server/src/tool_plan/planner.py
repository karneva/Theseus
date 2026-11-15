from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any, Awaitable, Callable, Literal

from src.config import resolve_model_name, settings
from src.remote_workspace.read_primitives import build_remote_read_analysis_tools
from src.remote_workspace.resolver import RemoteWorkspaceResolver, resolve_remote_workspace_config
from src.remote_workspace.runtime import (
    REMOTE_WORKSPACE_RUNTIME_KEY,
    register_remote_workspace_config,
)
from src.remote_workspace.schemas import RemoteWorkspaceConnectionConfig
from src.tool_plan.prompts import (
    PLAN_PROGRESS_CHUNK_MESSAGES,
    CUSTOM_TOOL_SAFETY_CONTEXT,
    PLAN_VALIDATION_FEEDBACK_SYSTEM_PROMPT,
    PLAN_FAILURE_FEEDBACK_SYSTEM_PROMPT,
    PLAN_STRUCTURED_OUTPUT_SYSTEM_PROMPT,
)
from src.tool_plan.artifact_context import (
    build_project_artifact_context,
    normalize_project_artifact_paths,
    build_existing_tools_context,
    compact_prompt_json,
)
from src.tool_plan.agent_loop import CheckpointCallback, ToolPlanAgentLoop
from src.tool_plan.display_markdown import build_plan_display_markdown
from src.tool_plan.errors import ToolPlanPlannerError
from src.tool_plan.snapshot_builder import PlanSnapshotBuilder
from src.tool_plan.execution_spec_validator import (
    is_generated_tool_request,
    validate_execution_spec_if_required as validate_plan_execution_spec,
)
from src.tool_plan.schemas import (
    ConversationHistoryItem,
    ToolPlanRegenerationRequestedEvent,
    ToolPlanRequestEvent,
    ToolPlanRequestedEvent,
    ToolPlanResult,
    ToolPlanSkippedResult,
)
from src.tool_plan.structured_output_schema import (
    plan_draft_response_format,
    plan_draft_vllm_extra_body,
)
from theseus_engine.engine.stream_events import extract_plan_json
from theseus_engine.models.modes import AgentMode, PlanPhase
from theseus_engine.models.messages import ConversationMessage, TextBlock
from theseus_engine.models.state import TheseusStateMachine
from theseus_engine.tools.core.base_tools import ToolRegistry
from theseus_engine.wrappers.llm_clients.api_types import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiTextDeltaEvent,
    SupportsStreamingMessages,
)
from theseus_engine.wrappers.llm_clients.theseus_client import TheseusLLMClient

ProgressCallback = Callable[[str, int], Awaitable[None] | None]
ChunkCallback = Callable[[str], Awaitable[None] | None]

logger = logging.getLogger(__name__)


class ToolPlanPlanner:
    """사용자의 자연어 요청을 검토 가능한 Tool 생성 계획으로 변환합니다.

    이 단계에서는 Python 코드를 직접 만들지 않습니다. 대화 이력과 프로젝트의 기존
    Tool 정보를 LLM에 전달하고, 그 결과를 실행 명세와 화면 표시용 스냅샷으로 정규화해
    사용자가 실제 생성 전에 범위와 권한을 확인할 수 있게 합니다.
    """

    def __init__(
        self,
        *,
        llm_client: SupportsStreamingMessages | None = None,
        model_name: str | None = None,
        remote_workspace_resolver: RemoteWorkspaceResolver | None = None,
    ) -> None:
        self.model_name = resolve_model_name(model_name)
        self.llm_client = llm_client or TheseusLLMClient(self.model_name)
        self.remote_workspace_resolver = remote_workspace_resolver
        self.snapshot_builder = PlanSnapshotBuilder()

    async def plan(
        self,
        event: ToolPlanRequestEvent,
        *,
        progress_callback: ProgressCallback | None = None,
        chunk_callback: ChunkCallback | None = None,
        status_chunk_callback: ChunkCallback | None = None,
        checkpoint: dict | None = None,
        checkpoint_callback: CheckpointCallback | None = None,
    ) -> ToolPlanResult | ToolPlanSkippedResult:
        # 자연어와 대화 맥락을 바탕으로 먼저 구조화 가능한 PLAN 초안을 생성합니다.
        await self._emit_progress(progress_callback, "PLAN_DRAFTING", 10)
        await self._emit_status_chunk(status_chunk_callback, "PLAN_DRAFTING")
        remote_workspace = await resolve_remote_workspace_config(
            project_id=event.project_id,
            remote_workspace_id=event.remote_workspace_id,
            resolver=self.remote_workspace_resolver,
        )
        generated = await self._generate(
            event,
            remote_workspace=remote_workspace,
            chunk_callback=chunk_callback,
            checkpoint=checkpoint,
            checkpoint_callback=checkpoint_callback,
        )
        if isinstance(generated, ToolPlanSkippedResult):
            return generated
        _raw_markdown, structured_plan = generated

        # 생성 요청에는 권한, 입력·출력, 검증 방법이 포함되어야 이후 빌드가 안전하게 진행됩니다.
        await self._emit_progress(progress_callback, "PLAN_STRUCTURING", 75)
        await self._emit_status_chunk(status_chunk_callback, "PLAN_STRUCTURING")
        try:
            validation_warnings = self._validate_execution_spec_if_required(structured_plan, event)
        except ToolPlanPlannerError as exc:
            await self._emit_progress(progress_callback, "PLAN_FEEDBACK", 95)
            await self._emit_status_chunk(status_chunk_callback, "PLAN_FEEDBACK")
            feedback = await self._generate_validation_failure_feedback(
                event,
                structured_plan=structured_plan,
                failure_message=str(exc),
                remote_workspace=remote_workspace,
            )
            return ToolPlanSkippedResult(message=feedback)
        version = self._resolve_plan_version(event)
        # 같은 계획을 API 저장용 JSON과 사용자 검토용 Markdown으로 각각 표현합니다.
        display_plan = self._normalize_project_artifacts_for_display(structured_plan, event)
        snapshot = self.snapshot_builder.build(
            display_plan,
            version=version,
            event=event,
            validation_warnings=validation_warnings,
        )
        structured = self._build_structured_plan(
            display_plan,
            validation_warnings=validation_warnings,
        )
        display_markdown = self._build_markdown(snapshot)

        await self._emit_progress(progress_callback, "PLAN_VALIDATING", 90)
        await self._emit_status_chunk(status_chunk_callback, "PLAN_VALIDATING")
        self.snapshot_builder.validate(snapshot)
        await self._emit_progress(progress_callback, "PLAN_COMPLETED", 100)
        await self._emit_status_chunk(status_chunk_callback, "PLAN_COMPLETED")

        return ToolPlanResult(
            rawMarkdown=display_markdown,
            structuredPlanJson=structured,
            planSnapshot=snapshot,
        )

    async def _generate(
        self,
        event: ToolPlanRequestEvent,
        *,
        remote_workspace: RemoteWorkspaceConnectionConfig | None,
        chunk_callback: ChunkCallback | None,
        checkpoint: dict | None = None,
        checkpoint_callback: CheckpointCallback | None = None,
    ) -> tuple[str, dict[str, Any]] | ToolPlanSkippedResult:
        """자연어 요청을 LLM에 전달하고 PLAN JSON으로 해석할 수 있는 결과를 반환합니다."""

        prompt = self._build_prompt(event)
        history_messages = self._history_messages(event)
        tool_registry = self._build_tool_registry(event, remote_workspace=remote_workspace)
        remote_workspace_runtime_key = (
            register_remote_workspace_config(remote_workspace)
            if remote_workspace is not None
            else None
        )
        agent_loop = ToolPlanAgentLoop(
            llm_client=self.llm_client,
            model_name=self.model_name,
            tool_registry=tool_registry,
            tool_metadata={
                "run_id": event.run_id,
                "project_id": event.project_id,
                "chat_session_id": event.chat_session_id,
                "user_id": getattr(event, "requested_by_user_id", None),
                "agent_mode": event.mode,
                "remote_workspace_id": event.remote_workspace_id,
                REMOTE_WORKSPACE_RUNTIME_KEY: remote_workspace_runtime_key,
                "remote_workspace": (
                    remote_workspace.redacted_model_dump(by_alias=True)
                    if remote_workspace is not None
                    else None
                ),
            },
        )
        loop_result = await agent_loop.run(
            initial_prompt=prompt,
            initial_messages=history_messages,
            system_prompt=self._build_system_prompt(
                event,
                available_tools=tuple(tool.name for tool in tool_registry.list_tools()),
            ),
            checkpoint=checkpoint,
            checkpoint_callback=checkpoint_callback,
            chunk_callback=chunk_callback,
        )

        # 모델별 구조화 출력 기능을 우선 사용하고, 지원하지 않으면 본문 속 JSON을 해석합니다.
        payload = await self._structured_plan_payload(
            event,
            candidate_text=loop_result.final_text,
            remote_workspace=remote_workspace,
        )
        if payload is None:
            payload = self._parse_plan_payload(loop_result.final_text)
        if payload is None:
            message = self._plain_chat_response(loop_result.final_text)
            if message:
                return ToolPlanSkippedResult(message=message)
            raise ToolPlanPlannerError(
                "Invalid PLAN draft LLM output: no PLAN JSON block was found."
            )
        return loop_result.final_text, payload

    async def _structured_plan_payload(
        self,
        event: ToolPlanRequestEvent,
        *,
        candidate_text: str,
        remote_workspace: RemoteWorkspaceConnectionConfig | None,
    ) -> dict[str, Any] | None:
        mode = settings.CORE_TOOL_PLAN_STRUCTURED_OUTPUT_MODE
        if mode == "off":
            return None

        attempts = self._structured_output_attempts(mode)
        if not attempts:
            return None

        prompt = self._build_structured_output_prompt(
            event,
            candidate_text=candidate_text,
            remote_workspace=remote_workspace,
        )
        messages = [ConversationMessage.from_user_text(prompt)]
        errors: list[str] = []

        for attempt_name, request_options in attempts:
            try:
                final_text = ""
                collected_text: list[str] = []
                async for llm_event in self.llm_client.stream_message(
                    ApiMessageRequest(
                        model=self.model_name,
                        messages=messages,
                        system_prompt=PLAN_STRUCTURED_OUTPUT_SYSTEM_PROMPT,
                        max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                        tools=[],
                        debug_context={
                            "run_id": event.run_id,
                            "project_id": event.project_id,
                            "chat_session_id": event.chat_session_id,
                            "agent_mode": event.mode,
                            "remote_workspace_id": event.remote_workspace_id,
                            "purpose": "plan_structured_output_formatter",
                            "structured_output_mode": mode,
                            "structured_output_attempt": attempt_name,
                        },
                        **request_options,
                    )
                ):
                    if isinstance(llm_event, ApiTextDeltaEvent):
                        collected_text.append(llm_event.text)
                    elif isinstance(llm_event, ApiMessageCompleteEvent):
                        final_text = llm_event.message.text
                payload = self._parse_plan_payload(final_text or "".join(collected_text))
                if payload is not None:
                    return payload
                errors.append(f"{attempt_name}: no parseable PLAN JSON returned")
            except Exception as exc:
                errors.append(f"{attempt_name}: {exc}")
                logger.warning(
                    "PLAN structured output formatting failed. runId=%s attempt=%s error=%s",
                    event.run_id,
                    attempt_name,
                    exc,
                    exc_info=True,
                )

        if mode == "strict":
            detail = "; ".join(errors) if errors else "structured output unavailable"
            raise ToolPlanPlannerError(f"PLAN structured JSON output failed: {detail}")
        return None

    def _structured_output_attempts(
        self,
        mode: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        response_format_attempt = (
            "response_format",
            {"response_format": plan_draft_response_format()},
        )
        vllm_attempt = (
            "vllm_structured_outputs",
            {"extra_body": plan_draft_vllm_extra_body()},
        )
        if mode == "response_format":
            return [response_format_attempt]
        if mode == "vllm_structured_outputs":
            return [vllm_attempt]
        if mode == "strict":
            attempts = [response_format_attempt]
            if self._is_vllm_model():
                attempts.append(vllm_attempt)
            return attempts
        if mode == "auto":
            attempts = [response_format_attempt]
            if self._is_vllm_model():
                attempts.append(vllm_attempt)
            return attempts
        return []

    def _is_vllm_model(self) -> bool:
        normalized = str(self.model_name or "").strip().lower()
        return normalized == "vllm" or normalized.startswith("vllm/")

    def _build_structured_output_prompt(
        self,
        event: ToolPlanRequestEvent,
        *,
        candidate_text: str,
        remote_workspace: RemoteWorkspaceConnectionConfig | None,
    ) -> str:
        remote_context = (
            {
                "remoteWorkspaceId": event.remote_workspace_id,
                "basePath": remote_workspace.base_path if remote_workspace else None,
                "allowWriteExecution": (
                    remote_workspace.allow_write_execution if remote_workspace else None
                ),
            }
            if event.remote_workspace_id is not None
            else None
        )
        request_text = (
            self._regeneration_request_summary(event)
            if isinstance(event, ToolPlanRegenerationRequestedEvent)
            else event.prompt
        )
        return (
            "User request:\n"
            f"{request_text}\n\n"
            "Runtime project custom tool artifact context:\n"
            f"{build_project_artifact_context(event.project_id)}\n\n"
            "Remote workspace context:\n"
            f"{json.dumps(remote_context, ensure_ascii=False, indent=2)}\n\n"
            "Candidate PLAN draft to normalize:\n"
            f"{candidate_text}\n\n"
            "Return the normalized PLAN as the existing Theseus PLAN Draft JSON object only."
        )

    def _build_prompt(self, event: ToolPlanRequestEvent) -> str:
        artifact_context = build_project_artifact_context(event.project_id)
        existing_tool_context = build_existing_tools_context(event.project_id)
        context_section = "\n\n".join(
            item for item in (artifact_context, existing_tool_context) if item
        )
        extra_context = f"\n\n{context_section}" if context_section else ""
        if isinstance(event, ToolPlanRegenerationRequestedEvent):
            feedback = [
                item.model_dump(mode="json", by_alias=True) for item in event.feedback_items
            ]
            return (
                "Revise the current plan according to this review feedback.\n\n"
                f"Base plan version: {event.base_plan_version}\n\n"
                "Base plan:\n"
                f"{json.dumps(event.base_plan.model_dump(mode='json', by_alias=True), ensure_ascii=False, indent=2)}\n\n"
                "Feedback:\n"
                f"{json.dumps(feedback, ensure_ascii=False, indent=2)}\n\n"
                f"{CUSTOM_TOOL_SAFETY_CONTEXT}"
                f"{extra_context}"
            )
        return f"{event.prompt}\n\n{CUSTOM_TOOL_SAFETY_CONTEXT}{extra_context}"

    def _history_messages(self, event: ToolPlanRequestEvent) -> list[ConversationMessage]:
        messages: list[ConversationMessage] = []
        for item in event.history:
            role = self._normalize_history_role(item.role)
            if role is None:
                continue
            content = self._render_history_content(item)
            if not content.strip():
                continue
            messages.append(
                ConversationMessage(
                    role=role,
                    content=[TextBlock(text=content)],
                )
            )
        return messages

    @staticmethod
    def _normalize_history_role(role: str) -> Literal["user", "assistant"] | None:
        normalized = str(role or "").strip().lower()
        if normalized in {"user", "assistant"}:
            return normalized
        return None

    def _render_history_content(self, item: ConversationHistoryItem) -> str:
        message_type = (item.message_type or "CHAT").upper()
        content_type = (item.content_type or "TEXT").upper()

        if message_type == "TOOL_FEEDBACK" and content_type == "JSON":
            return self._summarize_feedback_content(item.content)
        if message_type == "TOOL_APPROVAL_REQUEST":
            return "Requested tool approval."
        if isinstance(item.content, str):
            return item.content
        if item.content is None:
            return ""
        return json.dumps(item.content, ensure_ascii=False, indent=2)

    @staticmethod
    def _summarize_feedback_content(content: str | dict[str, Any] | list[Any] | None) -> str:
        if isinstance(content, str):
            try:
                payload = json.loads(content)
            except ValueError:
                return content
        else:
            payload = content

        if not isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=False, indent=2) if payload is not None else ""

        feedback_items = payload.get("feedbackItems", [])
        if not isinstance(feedback_items, list) or not feedback_items:
            return "Requested PLAN draft feedback changes."

        lines = [f"Requested {len(feedback_items)} PLAN draft revisions:"]
        for item in feedback_items:
            if not isinstance(item, dict):
                continue
            block_id = item.get("blockId", "unknown-block")
            comment = item.get("comment", "")
            lines.append(f"- {block_id}: {comment}")
        return "\n".join(lines)

    def _build_system_prompt(
        self,
        event: ToolPlanRequestEvent,
        *,
        available_tools: tuple[str, ...],
    ) -> str:
        phase = (
            PlanPhase.WAIT_FOR_REVIEW
            if isinstance(event, ToolPlanRegenerationRequestedEvent)
            else PlanPhase.DRAFTING
        )
        state_machine = TheseusStateMachine(initial_mode=AgentMode.PLAN)
        state_machine.plan_phase = phase
        if isinstance(event, ToolPlanRegenerationRequestedEvent):
            state_machine.plan = json.dumps(
                event.base_plan.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
        runtime_reminders = (build_project_artifact_context(event.project_id),)
        return state_machine.get_system_prompt(
            available_tools=available_tools,
            runtime_reminders=runtime_reminders,
        )

    def _build_tool_registry(
        self,
        event: ToolPlanRequestEvent,
        *,
        remote_workspace: RemoteWorkspaceConnectionConfig | None,
    ) -> ToolRegistry:
        del event
        registry = ToolRegistry()
        if remote_workspace is not None:
            for tool in build_remote_read_analysis_tools(remote_workspace):
                registry.register(tool)
        return registry

    async def _generate_validation_failure_feedback(
        self,
        event: ToolPlanRequestEvent,
        *,
        structured_plan: dict[str, Any],
        failure_message: str,
        remote_workspace: RemoteWorkspaceConnectionConfig | None,
    ) -> str:
        """Explain a rejected PLAN draft as an assistant response.

        This keeps invalid plans out of storage while still giving the user a
        useful next step instead of ending with a raw validation error.
        """

        prompt = self._build_validation_failure_feedback_prompt(
            event,
            structured_plan=structured_plan,
            failure_message=failure_message,
            remote_workspace=remote_workspace,
        )
        messages = [ConversationMessage.from_user_text(prompt)]
        try:
            final_text = ""
            collected_text: list[str] = []
            async for llm_event in self.llm_client.stream_message(
                ApiMessageRequest(
                    model=self.model_name,
                    messages=messages,
                    system_prompt=PLAN_VALIDATION_FEEDBACK_SYSTEM_PROMPT,
                    max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                    tools=[],
                    debug_context={
                        "run_id": event.run_id,
                        "project_id": event.project_id,
                        "chat_session_id": event.chat_session_id,
                        "agent_mode": event.mode,
                        "remote_workspace_id": event.remote_workspace_id,
                        "purpose": "plan_validation_feedback",
                    },
                )
            ):
                if isinstance(llm_event, ApiTextDeltaEvent):
                    collected_text.append(llm_event.text)
                elif isinstance(llm_event, ApiMessageCompleteEvent):
                    final_text = llm_event.message.text
            response = self._plain_chat_response(final_text or "".join(collected_text))
            if response:
                return response
        except Exception as exc:
            logger.warning(
                "PLAN validation feedback generation failed. runId=%s error=%s",
                event.run_id,
                exc,
                exc_info=True,
            )
        return self._fallback_validation_failure_feedback(
            event,
            failure_message=failure_message,
            structured_plan=structured_plan,
        )

    def _build_validation_failure_feedback_prompt(
        self,
        event: ToolPlanRequestEvent,
        *,
        structured_plan: dict[str, Any],
        failure_message: str,
        remote_workspace: RemoteWorkspaceConnectionConfig | None,
    ) -> str:
        plan_summary = {
            "goal": structured_plan.get("goal") or structured_plan.get("title"),
            "summary": structured_plan.get("summary"),
            "context": compact_prompt_json(structured_plan.get("context")),
            "tasks": compact_prompt_json(structured_plan.get("tasks")),
            "execution_spec": compact_prompt_json(structured_plan.get("execution_spec")),
            "alternatives": compact_prompt_json(structured_plan.get("alternatives")),
        }
        if isinstance(event, ToolPlanRegenerationRequestedEvent):
            request_text = self._regeneration_request_summary(event)
        else:
            request_text = event.prompt
        remote_context = (
            {
                "remoteWorkspaceId": event.remote_workspace_id,
                "basePath": remote_workspace.base_path if remote_workspace else None,
                "allowWriteExecution": (
                    remote_workspace.allow_write_execution if remote_workspace else None
                ),
            }
            if event.remote_workspace_id is not None
            else None
        )
        return (
            "The previous PLAN draft was rejected by Core validation before it could be saved.\n"
            "Analyze the failure and respond in the same language as the original user request.\n\n"
            "Original user request:\n"
            f"{request_text}\n\n"
            "Validation failure:\n"
            f"{failure_message}\n\n"
            "Remote Workspace context, redacted:\n"
            f"{json.dumps(remote_context, ensure_ascii=False, indent=2)}\n\n"
            "Rejected PLAN draft summary:\n"
            f"{json.dumps(plan_summary, ensure_ascii=False, indent=2)}\n"
        )

    @staticmethod
    def _regeneration_request_summary(event: ToolPlanRegenerationRequestedEvent) -> str:
        feedback = [item.model_dump(mode="json", by_alias=True) for item in event.feedback_items]
        return (
            "사용자가 기존 PLAN draft에 대한 수정 요청을 보냈습니다.\n"
            f"Base plan version: {event.base_plan_version}\n"
            f"Feedback: {json.dumps(feedback, ensure_ascii=False)}"
        )

    @staticmethod
    def _fallback_validation_failure_feedback(
        event: ToolPlanRequestEvent,
        *,
        failure_message: str,
        structured_plan: dict[str, Any],
    ) -> str:
        title = str(structured_plan.get("goal") or structured_plan.get("title") or "요청").strip()
        remote_line = (
            "\n\n선택된 Remote Workspace가 있으므로, 다음 PLAN draft는 원격 환경을 읽기 전용으로 분석하는 범위 안에서 다시 작성해야 합니다."
            if event.remote_workspace_id is not None
            else ""
        )
        return (
            f"생성된 PLAN draft가 Core 검증을 통과하지 못해 저장하지 않았습니다.\n\n"
            f"대상 요청: {title}\n\n"
            "주요 원인:\n"
            f"{failure_message}\n\n"
            "가능한 대안:\n"
            "1. `python3 -c`, `python3 <path>`, output redirection, shell chaining처럼 strict 모드에서 임의 실행으로 해석되는 패턴을 제거합니다.\n"
            "2. Docker/API/log 점검은 `docker ps/inspect/logs`, `df`, `free`, `top`, `uptime`, `curl`, `grep`, `awk`, `sed -n` 같은 읽기 전용 범주로 다시 작성합니다.\n"
            "3. 생성할 Tool 요청이라면 shell command 실행 계획보다 Tool의 동작, 입력, 출력, `validation_strategy=core_sandbox_gate` 중심으로 다시 요청합니다.\n"
            "4. md 파일 저장이 꼭 필요하면 저장 위치와 쓰기 승인을 명확히 한 별도 승인 흐름으로 분리합니다.\n\n"
            "다음 요청 예시:\n"
            "`허용된 remote read-only 도구만 사용해서 서비스별 코드 분석 PLAN draft를 다시 작성해줘. md 저장은 제외하고 Markdown 보고서 출력만 포함해줘.`"
            f"{remote_line}"
        )

    async def explain_failure(
        self,
        event: ToolPlanRequestEvent,
        *,
        code: str,
        message: str,
        stage: str | None = None,
    ) -> str:
        """Convert a raw PLAN worker failure into assistant-readable feedback."""

        prompt = self._build_failure_feedback_prompt(
            event,
            code=code,
            message=message,
            stage=stage,
        )
        try:
            final_text = ""
            collected_text: list[str] = []
            async for llm_event in self.llm_client.stream_message(
                ApiMessageRequest(
                    model=self.model_name,
                    messages=[ConversationMessage.from_user_text(prompt)],
                    system_prompt=PLAN_FAILURE_FEEDBACK_SYSTEM_PROMPT,
                    max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                    tools=[],
                    debug_context={
                        "run_id": event.run_id,
                        "project_id": event.project_id,
                        "chat_session_id": event.chat_session_id,
                        "agent_mode": event.mode,
                        "remote_workspace_id": event.remote_workspace_id,
                        "purpose": "plan_failure_feedback",
                        "failure_code": code,
                        "failure_stage": stage,
                    },
                )
            ):
                if isinstance(llm_event, ApiTextDeltaEvent):
                    collected_text.append(llm_event.text)
                elif isinstance(llm_event, ApiMessageCompleteEvent):
                    final_text = llm_event.message.text
            response = self._plain_chat_response(final_text or "".join(collected_text))
            if response:
                return response
        except Exception as exc:
            logger.warning(
                "PLAN failure feedback generation failed. runId=%s code=%s error=%s",
                event.run_id,
                code,
                exc,
                exc_info=True,
            )
        return self._fallback_plan_failure_feedback(code=code, message=message, stage=stage)

    def _build_failure_feedback_prompt(
        self,
        event: ToolPlanRequestEvent,
        *,
        code: str,
        message: str,
        stage: str | None,
    ) -> str:
        request_text = (
            self._regeneration_request_summary(event)
            if isinstance(event, ToolPlanRegenerationRequestedEvent)
            else event.prompt
        )
        return (
            "A PLAN generation worker failed. Explain it to the user in the same language as the original request or feedback, and suggest a safe retry path.\n\n"
            f"runId={event.run_id}\n"
            f"projectId={event.project_id}\n"
            f"chatSessionId={event.chat_session_id}\n"
            f"mode={event.mode}\n"
            f"remoteWorkspaceId={event.remote_workspace_id}\n"
            f"failureCode={code}\n"
            f"failureStage={stage or 'unknown'}\n\n"
            "Original user request or regeneration feedback:\n"
            f"{request_text}\n\n"
            "Raw failure message:\n"
            f"{message}\n"
        )

    @staticmethod
    def _fallback_plan_failure_feedback(*, code: str, message: str, stage: str | None) -> str:
        lowered = message.lower()
        duplicate_hint = any(
            needle in lowered
            for needle in (
                "이미 존재",
                "already exists",
                "duplicate",
                "filename",
                "modulename",
            )
        )
        next_step = (
            "기존 Tool을 재사용/확장할지, 새 toolName/moduleName/fileName으로 다시 생성할지 선택해 다시 요청해야 합니다."
            if duplicate_hint
            else "오류 원인을 반영해 더 좁은 범위의 PLAN draft로 다시 요청하거나, 필요한 승인/환경 조건을 먼저 정리해야 합니다."
        )
        return (
            "PLAN 생성 작업이 실패했습니다.\n\n"
            f"- code: {code}\n"
            f"- stage: {stage or 'unknown'}\n"
            f"- 원인: {message}\n"
            f"- 다음 단계: {next_step}"
        )

    def _resolve_plan_version(self, event: ToolPlanRequestEvent) -> int:
        if isinstance(event, ToolPlanRegenerationRequestedEvent):
            return event.base_plan_version + 1
        return 1

    def _build_structured_plan(
        self,
        plan_json: dict[str, Any],
        *,
        validation_warnings: list[str] | None = None,
    ) -> dict:
        structured = dict(plan_json)
        if validation_warnings:
            structured["execution_spec_validation"] = {
                "mode": settings.CORE_TOOL_PLAN_EXECUTION_SPEC_VALIDATION_MODE,
                "warnings": list(validation_warnings),
            }
        return structured

    def _normalize_project_artifacts_for_display(
        self,
        plan_json: dict[str, Any],
        event: ToolPlanRequestEvent,
    ) -> dict[str, Any]:
        if not is_generated_tool_request(plan_json, event):
            return plan_json
        normalized = deepcopy(plan_json)
        return normalize_project_artifact_paths(normalized, event.project_id)

    def _build_markdown(self, snapshot: dict) -> str:
        return build_plan_display_markdown(snapshot)

    def _validate_execution_spec_if_required(
        self,
        plan_json: dict[str, Any],
        event: ToolPlanRequestEvent,
    ) -> list[str]:
        validation_mode = settings.CORE_TOOL_PLAN_EXECUTION_SPEC_VALIDATION_MODE
        result = validate_plan_execution_spec(
            plan_json,
            event,
            validation_mode=validation_mode,
        )
        if result.errors:
            if validation_mode == "warn":
                return [*result.warnings, *result.errors]
            details = "\n".join(f"- {item}" for item in result.errors)
            raise ToolPlanPlannerError("PLAN draft execution spec invalid:\n" + details)
        return result.warnings

    @staticmethod
    def _extract_json_object(text: str) -> str:
        stripped = text.strip()
        fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
        if fence_match:
            stripped = fence_match.group(1).strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return stripped[start : end + 1]
        raise ValueError("No JSON object found")

    @classmethod
    def _parse_plan_payload(cls, text: str) -> dict[str, Any] | None:
        payload = extract_plan_json(text)
        if payload is not None:
            return payload
        try:
            parsed = json.loads(cls._extract_json_object(text))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _plain_chat_response(text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        fence_match = re.fullmatch(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)\s*```", stripped, re.DOTALL)
        if fence_match:
            return fence_match.group(1).strip()
        return stripped

    async def _emit_progress(
        self, callback: ProgressCallback | None, message: str, rate: int
    ) -> None:
        if callback is None:
            return
        result = callback(message, rate)
        if result is not None:
            await result

    async def _emit_status_chunk(self, callback: ChunkCallback | None, message: str) -> None:
        content = PLAN_PROGRESS_CHUNK_MESSAGES.get(message, "")
        await self._emit_chunk(callback, content)

    async def _emit_chunk(self, callback: ChunkCallback | None, content: str) -> None:
        if callback is None or not content:
            return
        result = callback(content)
        if result is not None:
            await result
