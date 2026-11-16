import os
from pathlib import Path
from typing import Optional

from theseus_engine.engine.query_engine import QueryEngine
from theseus_engine.tools.core.base_tools import ToolRegistry

from theseus_engine.wrappers.llm_clients.theseus_client import TheseusLLMClient
from theseus_engine.models.modes import AgentMode
from theseus_engine.models.state import TheseusStateMachine
from theseus_engine.tools.core import (
    ALL_CORE_TOOLS,
    load_custom_tools,
    load_custom_tools_for_project,
)
from theseus_engine.tools.core.custom_tool_paths import workspace_custom_tool_dirs
from theseus_engine.tools.tool_repair import ToolRepairPolicy
from theseus_engine.core.tool_visibility import (
    ToolVisibilityPolicy,
    active_tool_names,
    build_visible_registry,
    can_create_tool_for_state,
)
from theseus_engine.config import get_tool_rag_settings, stream_max_agent_turns
from theseus_engine.models.rbac import TheseusPermissionChecker
from theseus_engine.wrappers.hooks.theseus_hook_executor import (
    TheseusHookExecutor,
)
from theseus_engine.observability.tracer import is_tracing_enabled
from theseus_engine.observability.stats import (
    SessionStats,
)  # noqa: F401 (reset_stats 경로에서 사용)
from theseus_engine.engine.cost_tracker import CostTracker
from theseus_engine.memory.scoped_memory import ScopedMemory
from theseus_engine.core.tool_rag.assembly import (
    PROVENANCE_METADATA_KEY,
    aselect_tools_for_turn,
)
from theseus_engine.skills.injection import SkillInjectionConfig

# 동적 도구 선택(Tool RAG) 기본값: THESEUS_TOOL_RAG_ENABLED(구 THESEUS_DYNAMIC_TOOL_RETRIEVAL)
THESEUS_DYNAMIC_TOOL_RETRIEVAL = get_tool_rag_settings().enabled


def _workspace_custom_tool_dirs(cwd: Path) -> list[Path]:
    """Return custom tool dirs owned by the active workspace."""
    return workspace_custom_tool_dirs(cwd)


ENGINE_RAG_TOOL_NAMES = frozenset({"search_knowledge_base", "ingest_document"})


def unavailable_engine_rag_tools() -> frozenset[str]:
    """로컬 임베딩 의존성이 없어 호출하면 ImportError가 나는 엔진 RAG 도구 이름.

    EMBEDDING_PROVIDER 기본값은 local(sentence-transformers)인데, 이 패키지는 기본 requirements.txt에서 빠지고
    requirements-torch.txt로 옮겨졌습니다. 그 상태에서 두 도구를 보이게 두면 Tool RAG 슬롯에도 들어가고, 모델이
    호출하면 실패합니다. 서버는 THESEUS_ENABLE_ENGINE_RAG_TOOLS(기본 false)로 따로 숨깁니다.
    """
    import importlib.util

    provider = (os.getenv("EMBEDDING_PROVIDER") or "local").strip().lower()
    if provider != "local":
        return frozenset()
    try:
        available = importlib.util.find_spec("sentence_transformers") is not None
    except (ImportError, ValueError):
        available = False
    return frozenset() if available else ENGINE_RAG_TOOL_NAMES


def _resolve_skill_injection_enabled(value: Optional[bool]) -> bool:
    if value is not None:
        return bool(value)
    raw = os.getenv("THESEUS_SKILL_AUTO_INJECTION", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _ensure_registry_tool_permissions(
    registry: ToolRegistry,
    project_tool_permissions: dict,
) -> dict:
    """Fill missing tool permission entries from registered tool metadata.

    Server assembly already infers permission levels from the full registry.
    Local/extension/TUI runtimes should do the same so newly added core tools
    such as worktree helpers or report writers are governed by their declared
    permission_level instead of falling back to an implicit level 1 at execution.
    The input mapping is updated in place because command handlers reuse it
    when rebuilding visible registries after mode/phase changes.
    """

    for tool in registry.list_tools():
        project_tool_permissions.setdefault(
            tool.name,
            getattr(tool, "permission_level", 1),
        )
    return project_tool_permissions


async def setup_engine(
    sm: TheseusStateMachine,
    user_level: int,
    project_tool_permissions: dict,
    permission_prompt_func,
    # ── 프로젝트/역할 기반 툴 가시성 ─────────────────────
    project_id: Optional[str] = None,
    actor_role: str = "MEMBER",
    project_disabled_tools: Optional[set] = None,
    # ── 기존 파라미터 ────────────────────────────────────
    user_query: Optional[str] = None,
    top_k: int = 10,
    history_messages: Optional[list] = None,
    api_client: Optional[TheseusLLMClient] = None,
    enable_dynamic_tools: bool = THESEUS_DYNAMIC_TOOL_RETRIEVAL,
    enable_skill_injection: Optional[bool] = None,
    runtime_reminders: Optional[tuple[str, ...]] = None,
    reset_stats: bool = False,
    # ── Kafka 실행 추적 ID (선택) ─────────────────────────
    run_id: Optional[str] = None,
    tool_draft_id: Optional[str] = None,
    # ── 워크스페이스 경로 (멀티유저 서버 모드) ─────────────
    cwd: Optional[Path] = None,
):
    # ── 워크스페이스 경로 결정 ─────────────────────────────
    # cwd 파라미터 우선, 없으면 프로세스 현재 디렉토리 (standalone 호환)
    resolved_cwd = cwd if cwd is not None else Path.cwd()

    # ── 통계/비용 추적기: 요청 스코프 인스턴스 ─────────────
    # 싱글톤 reset()을 사용하면 동시 요청 간 통계가 뒤섞이므로
    # 항상 새 인스턴스를 생성한다. standalone CLI/TUI는 reset_stats=True
    # 로 호출하던 것을 그대로 유지하되 전역 싱글톤은 건드리지 않는다.
    tracker = CostTracker()
    stats = SessionStats()
    if reset_stats:
        # standalone 모드: 전역 싱글톤도 동기화 (CLI /cost, /stats 명령용)
        CostTracker._instance = tracker
        SessionStats._instance = stats

    scoped_memory = ScopedMemory(cwd=resolved_cwd)
    scoped_memory.ensure_gitignore()
    memory_context = scoped_memory.read_context()

    model_name = os.getenv("THESEUS_MODEL") or "gpt-4o"
    if api_client is None:
        api_client = TheseusLLMClient(model_name)

    # Theseus 자체 ToolRegistry로 시작 — create_default_tool_registry() 사용하지 않음
    full_registry = ToolRegistry()

    # ALL_CORE_TOOLS에서 모든 핵심 도구를 자동 등록
    for tool_cls in ALL_CORE_TOOLS:
        full_registry.register(tool_cls())

    # ── 커스텀 툴 로딩: project_id 유무에 따라 경로 분기 ──────
    custom_tool_inventory: list[dict] = []
    if project_id:
        loaded_tools = load_custom_tools_for_project(
            full_registry,
            project_id,
            project_tool_permissions,
            load_report=custom_tool_inventory,
        )
    else:
        loaded_tools = load_custom_tools(
            full_registry,
            project_tool_permissions,
            extra_dirs=_workspace_custom_tool_dirs(resolved_cwd),
            load_report=custom_tool_inventory,
        )
    if loaded_tools:
        print(f"✅ Loaded {len(loaded_tools)} custom tools.")

    project_tool_permissions = _ensure_registry_tool_permissions(
        full_registry,
        project_tool_permissions,
    )

    # Theseus 자체 PermissionSettings 사용
    from theseus_engine.models.rbac import TheseusPermissionSettings

    settings = TheseusPermissionSettings()
    permission_checker = TheseusPermissionChecker(
        settings,
        user_level,
        project_tool_permissions,
        require_human_confirm=False,
    )

    enable_hooks = os.getenv("THESEUS_ENABLE_AGENT_HOOK", "false").lower() == "true"
    hook_executor = None

    can_create_tool = can_create_tool_for_state(
        mode=sm.mode,
        plan_phase=getattr(sm, "plan_phase", None),
        project_id=project_id,
        actor_role=actor_role,
    )

    # ── 보이는 도구(모드·계획 단계·RBAC·프로젝트 비활성) ─────────────
    visibility_policy = ToolVisibilityPolicy(
        mode=sm.mode,
        plan_phase=getattr(sm, "plan_phase", None),
        user_level=user_level,
        tool_permissions=project_tool_permissions,
        can_create_tool=can_create_tool,
        disabled_tools=frozenset(project_disabled_tools or set()) | unavailable_engine_rag_tools(),
    )
    search_injectable_registry = build_visible_registry(
        full_registry,
        visibility_policy,
    )
    search_injectable_tool_names = active_tool_names(search_injectable_registry)

    # ── 동적 도구 선택(Tool RAG v2): 보이는 도구 중 필수 + 비용 인지 슬롯만 보냄 ─────
    # top_k는 v1 시그니처 호환용으로만 남아 있습니다(v2는 비용 예산이 슬롯 수를 정함).
    del top_k
    if enable_dynamic_tools and user_query:
        print("🔍 질의 기반 도구 선택 중...")
        selection = await aselect_tools_for_turn(
            full_registry=full_registry,
            visible_registry=search_injectable_registry,
            user_query=user_query,
            history_messages=history_messages,
            pinned=("create_tool",) if can_create_tool else (),
        )
    else:
        selection = await aselect_tools_for_turn(
            full_registry=full_registry,
            visible_registry=search_injectable_registry,
            user_query=None,
        )
    active_registry = selection.registry
    if selection.mode == "retrieved":
        print(f"🎯 선택된 도구: {', '.join(selection.names)}")
        if selection.is_none:
            print("⚠️ 맞는 도구가 없다고 판단 → 상위 일부 + ToolSearchTool로 보냄")
    elif enable_dynamic_tools and user_query and selection.reason.startswith("error"):
        print("⚠️ 도구 검색 중 오류 발생. 보이는 도구 전부를 사용합니다.")

    active_tool_names_tuple = active_tool_names(active_registry)
    tool_rag_provenance = dict(selection.provenance)
    if enable_hooks:
        hook_executor = TheseusHookExecutor(
            active_registry=active_registry,
            full_registry=full_registry,
            injectable_names=search_injectable_tool_names,
            provenance=tool_rag_provenance,
            enable_dynamic_tools=enable_dynamic_tools,
            permission_prompt=permission_prompt_func,
            llm_client=api_client,
            audit_tools={"write_file", "edit_file", "local_write_report"},
        )

    # ==============================================================

    engine = QueryEngine(
        api_client=api_client,
        tool_registry=active_registry,
        permission_checker=permission_checker,
        hook_executor=hook_executor,
        cwd=resolved_cwd,
        model=model_name,
        system_prompt=(
            sm.get_system_prompt(
                available_tools=active_tool_names_tuple,
                runtime_reminders=tuple(runtime_reminders or ()) + selection.runtime_reminders(),
            )
            + ("\n\n" + memory_context if memory_context else "")
        ),
        max_turns=stream_max_agent_turns(),
        permission_prompt=permission_prompt_func if callable(permission_prompt_func) else None,
        skill_injection_config=SkillInjectionConfig(
            enabled=_resolve_skill_injection_enabled(enable_skill_injection),
        ),
        tool_metadata={
            "tool_registry": full_registry,
            "tool_permissions": project_tool_permissions,
            "active_registry": active_registry,
            "search_injectable_tool_names": search_injectable_tool_names,
            PROVENANCE_METADATA_KEY: tool_rag_provenance,
            "custom_tool_inventory": custom_tool_inventory,
            "llm_client": api_client,
            "model_name": model_name,
            "tool_repair_policy": ToolRepairPolicy.from_env(),
            "cost_tracker": tracker,
            "session_stats": stats,
            "scoped_memory": scoped_memory,
            "user_rbac_level": user_level,
            "user_level": user_level,
            "agent_mode": sm.mode.value if hasattr(sm, "mode") else "normal",
            "plan_phase": (
                sm.plan_phase.value if getattr(sm, "plan_phase", None) is not None else None
            ),
            "project_id": project_id,
            "actor_role": actor_role,
            "active_skills": [],
            # Kafka 실행 추적 ID — ToolExecutionContext.run_id/tool_draft_id로 전달됨
            "run_id": run_id,
            "tool_draft_id": tool_draft_id,
        },
    )

    if is_tracing_enabled():
        import logging

        _log = logging.getLogger(__name__)
        _log.info(
            "[Observability] LangSmith 트레이싱 활성화. " "RBAC Lv.%d | Model: %s | Mode: %s",
            user_level,
            model_name,
            sm.mode.value,
        )

    return engine, full_registry


def get_tracing_tags(
    user_level: int,
    model_name: str,
    session_name: str = "default",
) -> list[str]:
    """LangSmith Run에 부착할 태그 목록을 생성합니다."""
    return [
        f"rbac_lv{user_level}",
        f"model:{model_name}",
        f"session:{session_name}",
    ]


def get_tracing_metadata(
    user_level: int,
    model_name: str,
    session_name: str = "default",
) -> dict:
    """LangSmith Run에 부착할 메타데이터를 생성합니다."""
    return {
        "rbac_level": user_level,
        "model": model_name,
        "session": session_name,
        "platform": "theseus-core-server",
    }
