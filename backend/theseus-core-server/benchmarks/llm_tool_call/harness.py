"""운영 서버 경로로 요청을 재현하고 LLM의 도구 호출을 채점합니다.

재현 방식
  * 질의마다 src.builder.engine.get_query_engine(EngineBuildContext(...))으로 서버 엔진을 그대로 조립합니다.
    시스템 프롬프트, 가시성·RBAC 필터, Tool RAG 선택, 도구 스키마 변환, 메시지 변환, 스트리밍 파싱, 도구 실행,
    훅이 모두 운영 코드 그대로입니다.
  * 엔진의 LLM 클라이언트를 RecordingClient로 감싸 턴마다 요청·응답을 기록하고, 다음 경우에 멈춥니다.
      - 모델이 정답 도구를 불렀을 때(성공)
      - 탐색용 읽기 전용 도구(SAFE_TOOLS)가 아닌 도구를 불렀을 때(그 도구는 실행하지 않음)
      - 도구 없이 답했을 때, 또는 max_turns에 닿았을 때
    SAFE_TOOLS만 부르면 엔진이 그 도구를 고정 프로젝트 사본(fixture)에서 실제로 실행하고 다음 턴으로 갑니다.
  * 운영과 다른 점(재현성 때문)
      - 시스템 프롬프트의 환경 섹션을 운영 Core 컨테이너 값으로 고정합니다(날짜만 상수).
      - 요청에 seed를 넣습니다. temperature 등 나머지 샘플링 값은 운영처럼 보내지 않아 Ollama Modelfile
        기본값을 씁니다(--temperature를 주면 그 값을 보냄).
      - Tool RAG 모델을 미리 워밍업합니다(운영에서는 워밍업 전 요청이 보이는 도구 전부를 받음).
      - 작업 디렉터리는 fixture(이 서버 코드의 git 스냅샷, benchmarks/ 제외)입니다.

채점 정의는 README.md "지표"를 보세요.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 운영 Core 컨테이너(theseus-core, python:3.11-slim)에서 get_environment_section()이 돌려준 값. 날짜만 고정.
PINNED_ENVIRONMENT_SECTION = "\n".join(
    [
        "# Environment",
        "- OS: Linux 7.0.0-1012-aws",
        "- Architecture: x86_64",
        "- Shell: unknown",
        "- Working directory: /app",
        "- Date: 2026-11-24 (UTC)",
        "- Python: 3.11.18",
        "- Python executable: /opt/venv/bin/python",
        "- Git: no",
    ]
)

# 실제로 실행해 결과를 돌려주는 탐색용 도구. 파일을 바꾸거나 밖으로 나가는 도구는 넣지 않습니다.
SAFE_TOOLS = frozenset(
    {
        "read_file",
        "glob",
        "grep",
        "lsp",
        "tool_search",
        "list_mcp_resources",
        "memory_list",
        "memory_read",
        "skill_list",
        "skill_read",
        "task_list",
        "task_get",
        "custom_tool_read_source",
    }
)
# 정답이 none(맞는 도구 없음)인 질의에서 허용하는 행동: 커스텀 도구 탐색/생성.
NONE_OK_TOOLS = frozenset({"tool_search", "create_tool"})
# 되묻기: 서버(웹 채팅)에서는 ask_user가 사용자에게 닿지 않으므로(이슈 #59) 본문으로 되묻는 것도 정답으로 칩니다.
CLARIFY_TOOLS = frozenset({"ask_user"})
_CLARIFY_TEXT = re.compile(
    r"\?|알려\s*주|말씀해\s*주|공유해\s*주|첨부해\s*주|붙여\s*주|보내\s*주|올려\s*주|제공해\s*주|지정해\s*주|정해\s*주|선택해\s*주|"
    r"확인해\s*주시|주시겠|주실\s*수|"
    r"please (provide|share|confirm|clarify|specify|send|attach|let me know|choose|tell)|could you|which (one|option)",
    re.IGNORECASE,
)


def is_clarifying_text(text: str) -> bool:
    """도구 호출 없이 사용자에게 필요한 정보를 되묻는 본문인지(물음표나 요청형 표현)."""
    return bool(text and text.strip() and _CLARIFY_TEXT.search(text))


def apply_clarify_rule(item: dict) -> dict:
    """정답에 ask_user가 있는 질의에서, 도구 없이 되묻는 본문으로 끝난 경우를 성공으로 칩니다(score_case와 같은 규칙).

    이미 저장된 결과(per_item)를 다시 채점할 때도 씁니다. 저장된 본문은 400자로 잘려 있지만 판정에는 충분합니다.
    """
    rel = set(item.get("relevant") or [])
    item["clarify_text"] = False
    if item["type"] == "none" or not (rel & CLARIFY_TOOLS) or item.get("error") is not None:
        return item
    turns = item["turns"]
    if turns and not turns[0]["calls"] and is_clarifying_text(turns[0]["text"]):
        item["success_at_1"] = True
        item["clarify_text"] = True
    if item["stop"] == "text_answer" and turns and not turns[-1]["calls"] and is_clarifying_text(turns[-1]["text"]):
        item["success_at_k"] = item["success_at_k_valid"] = True
        item["clarify_text"] = True
    return item


_TEXT_TOOL_CALL = re.compile(r"<tool_call>|\"(name|function)\"\s*:\s*\"[a-z_]+\"\s*,\s*\"(arguments|parameters)\"")


class _StopEpisode(Exception):
    """에피소드를 멈추는 신호(엔진은 이것을 API 오류로 처리하고 종료하며, 남은 도구는 실행하지 않음)."""


@dataclass
class TurnRecord:
    calls: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    stop_reason: str | None = None
    latency_s: float | None = None
    ttft_s: float | None = None
    request_tools: list[str] = field(default_factory=list)


@dataclass
class Episode:
    turns: list[TurnRecord] = field(default_factory=list)
    stop: str | None = None
    error: str | None = None
    system_prompt: str = ""


class RecordingClient:
    """엔진의 API 클라이언트를 감싸 턴별 요청·응답을 기록하고 멈출 시점을 정합니다."""

    def __init__(self, inner: Any, *, extra_body: dict[str, Any] | None, relevant: set[str], max_turns: int) -> None:
        self._inner = inner
        self._extra_body = extra_body
        self._relevant = relevant
        self._max_turns = max_turns
        self.episode = Episode()

    async def stream_message(self, request: Any):
        from theseus_engine.models.messages import TextBlock, ToolUseBlock
        from theseus_engine.wrappers.llm_clients.api_types import ApiMessageCompleteEvent, ApiTextDeltaEvent

        if not request.tools:
            # 루프 평가기·감사 같은 보조 호출(도구 없음): 모델이 이미 답을 끝낸 것이므로 멈춥니다.
            self.episode.stop = self.episode.stop or "aux_call"
            raise _StopEpisode("auxiliary LLM call")
        if len(self.episode.turns) >= self._max_turns:
            self.episode.stop = "max_turns"
            raise _StopEpisode("max turns")
        if self._extra_body:
            request = dataclasses.replace(request, extra_body={**(request.extra_body or {}), **self._extra_body})
        if not self.episode.turns:
            self.episode.system_prompt = request.system_prompt or ""
        turn = TurnRecord(request_tools=[t.get("name", "") for t in request.tools])
        started = time.perf_counter()
        async for event in self._inner.stream_message(request):
            if isinstance(event, ApiTextDeltaEvent) and turn.ttft_s is None:
                turn.ttft_s = time.perf_counter() - started
            if isinstance(event, ApiMessageCompleteEvent):
                turn.latency_s = time.perf_counter() - started
                turn.stop_reason = event.stop_reason
                for block in event.message.content:
                    if isinstance(block, ToolUseBlock):
                        turn.calls.append({"name": block.name, "input": block.input})
                    elif isinstance(block, TextBlock):
                        turn.text += block.text
                self.episode.turns.append(turn)
                names = [c["name"] for c in turn.calls]
                if not names:
                    self.episode.stop = "text_answer"
                    raise _StopEpisode("no tool call")
                if any(n in self._relevant for n in names):
                    self.episode.stop = "relevant_call"
                    raise _StopEpisode("relevant tool called")
                if any(n not in SAFE_TOOLS for n in names):
                    self.episode.stop = "other_action"
                    raise _StopEpisode("non-exploration tool called")
                yield event  # 탐색 도구만: 엔진이 실행하고 다음 턴으로
                continue
            yield event


def pin_environment_section() -> None:
    import theseus_engine.prompts.builder as prompt_builder

    prompt_builder.get_environment_section = lambda: PINNED_ENVIRONMENT_SECTION


def warmup_tool_rag() -> float:
    """운영 기동 시 워밍업(start_tool_rag_warmup)과 같은 레지스트리로 동기 워밍업합니다."""
    from theseus_engine.core.tool_rag import get_tool_retriever
    from theseus_engine.tools.core import ALL_CORE_TOOLS
    from theseus_engine.tools.core.base_tools import ToolRegistry

    registry = ToolRegistry()
    for tool_cls in ALL_CORE_TOOLS:
        registry.register(tool_cls())
    started = time.perf_counter()
    get_tool_retriever().warmup(registry)
    return time.perf_counter() - started


def make_fixture(server_dir: Path) -> Path:
    """이 서버 코드의 git HEAD 스냅샷(benchmarks/ 제외)을 임시 디렉터리에 풀고 그 경로를 돌려줍니다.

    평가셋 파일이 들어 있는 benchmarks/는 빼서 모델이 질의 원문을 찾아 읽지 못하게 합니다.
    """
    root = Path(tempfile.mkdtemp(prefix="llm-toolcall-fixture-"))
    archive = root / "snapshot.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD", "."],
        cwd=server_dir,
        check=True,
        capture_output=True,
    )
    project = root / "project"
    project.mkdir()
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if not (m.name == "benchmarks" or m.name.startswith("benchmarks/"))]
        tar.extractall(project, members=members, filter="data")
    archive.unlink()
    return project


# 경로 뒤에 한글 조사가 바로 붙으므로(예: config.py에) 경계는 ASCII 문자로만 봅니다. 앞에 *가 있으면 glob 패턴이라 뺍니다.
_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_./*-])((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|toml|txt|md|json|ya?ml|ts|tsx|js|jsx|cfg|ini|env|sh|sql|lock|csv|log|html|css|java|gradle|xml|properties|conf))(?![A-Za-z0-9_/])"
    r"|(?<![A-Za-z0-9_./*-])((?:[A-Za-z0-9_.-]+/)*(?:Dockerfile|Makefile|\.env|\.gitignore))(?![A-Za-z0-9_/])"
)
_IDENT_TOKEN = re.compile(
    r"'([^']{2,60})'|\"([^\"]{2,60})\"|(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|[A-Z][A-Z0-9]{2,})(?![A-Za-z0-9_])"
)


_CREATE_INTENT = re.compile(r"새로|새 파일|만들어|생성|초안|처음부터|scaffold|create|new", re.IGNORECASE)


def add_referenced_stubs(project: Path, cases: list[dict]) -> list[str]:
    """질의에 나온 파일 경로가 fixture에 없으면 자리표시 파일을 만듭니다(모델이 '파일 없음'으로 답하는 잡음을 줄임).

    내용에는 질의에 나온 식별자·따옴표 문자열을 한 줄씩 넣어, 수정 요청이 가리키는 대상이 파일 안에 있게 합니다.
    만든 상대 경로 목록을 돌려줍니다(결과 meta에 기록).
    """
    stubs: dict[str, list[str]] = {}
    for case in cases:
        query = case["query"]
        if _CREATE_INTENT.search(query):
            continue  # 새 파일을 만들라는 요청: 파일이 없어야 맞는 상황
        idents = [next(g for g in m.groups() if g) for m in _IDENT_TOKEN.finditer(query)]
        for m in _PATH_TOKEN.finditer(query):
            rel = m.group(1) or m.group(2)
            if rel.startswith("./"):
                rel = rel[2:]
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            bucket = stubs.setdefault(rel, [])
            for ident in idents:
                if ident not in bucket and ident != rel and not rel.endswith(ident):
                    bucket.append(ident)
    created = []
    for rel, idents in sorted(stubs.items()):
        target = project / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        comment = "//" if target.suffix in {".ts", ".tsx", ".js", ".jsx", ".java", ".gradle"} else "#"
        lines = [f"{comment} benchmark placeholder: {rel}"]
        for ident in idents:
            lines.append(f'{ident} = ""' if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident) else f"{comment} {ident}")
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        created.append(rel)
    return created


def enter_fixture(project: Path, server_dir: Path) -> None:
    # -m 실행이면 sys.path[0]이 ''(현재 디렉터리)라서, chdir 뒤에도 원래 코드가 import되도록 절대 경로를 앞에 둡니다.
    if str(server_dir) not in sys.path[:1]:
        sys.path.insert(0, str(server_dir))
    os.chdir(project)


def _remote_workspace_config():
    from benchmarks.tool_rag.harness import _remote_config

    return _remote_config(allow_write=True)


async def run_case(case: dict, *, extra_body: dict[str, Any] | None, timeout_s: float, max_turns: int) -> dict:
    """질의 하나를 운영 경로로 보내고 채점 결과를 돌려줍니다."""
    from src.builder.engine import EngineBuildContext, get_query_engine
    from theseus_engine.models.modes import AgentMode

    remote = case["registry"] == "server_remote"
    context = EngineBuildContext(
        user_level=5,
        project_tool_permissions={},
        mode=AgentMode.AGENT,
        approval_policy="reject",
        user_query=case["query"],
        history_messages=[],
        session_id=f"bench:{case['id']}",
        remote_workspace_id=1 if remote else None,
        remote_workspace=_remote_workspace_config() if remote else None,
    )
    assembly = get_query_engine(context)
    engine = assembly.engine
    relevant = set(case.get("relevant") or [])
    recorder = RecordingClient(engine.api_client, extra_body=extra_body, relevant=relevant, max_turns=max_turns)
    engine.set_api_client(recorder)
    registry = engine.tool_metadata["tool_registry"]

    async def _drive() -> None:
        async for _event in engine.submit_message(case["query"]):
            pass

    try:
        await asyncio.wait_for(_drive(), timeout=timeout_s)
    except asyncio.TimeoutError:
        recorder.episode.error = f"timeout after {timeout_s}s"
    if not recorder.episode.turns and recorder.episode.error is None:
        recorder.episode.error = "no completed LLM response (API error)"
    if recorder.episode.stop is None and recorder.episode.error is None:
        recorder.episode.stop = "engine_ended"
    return score_case(case, recorder.episode, registry, list(assembly.sent_tools), assembly.tool_selection_mode)


def score_case(case: dict, ep: Episode, registry: Any, sent_tools: list[str], selection_mode: str) -> dict:
    relevant = list(case.get("relevant") or [])
    rel = set(relevant)
    is_none = case["type"] == "none"
    for turn in ep.turns:
        offered = set(turn.request_tools)
        for call in turn.calls:
            call["offered"] = call["name"] in offered
            call["args_valid"], call["args_error"] = _validate_args(registry, call)
    turns = ep.turns
    first_turn = turns[0].calls if turns else []
    all_calls = [c for t in turns for c in t.calls]
    called = [c["name"] for c in all_calls]

    if is_none:
        s1 = bool(turns) and all(c["name"] in NONE_OK_TOOLS for c in first_turn)
        # 탐색은 괜찮지만, 맞는 도구가 없는데 다른 작업 도구를 실행하려 하면 실패.
        sk = bool(turns) and all(c["name"] in NONE_OK_TOOLS or c["name"] in SAFE_TOOLS for c in all_calls)
        sk_valid = sk
        retrievable = None
    else:
        s1 = any(c["name"] in rel for c in first_turn)
        sk = any(n in rel for n in called)
        sk_valid = any(c["name"] in rel and c["args_valid"] for c in all_calls)
        retrievable = bool(set(sent_tools) & rel)
    if ep.error is not None:
        s1 = sk = sk_valid = False
    first_text = turns[0].text if turns else ""
    return apply_clarify_rule({
        "id": case["id"],
        "lang": case["lang"],
        "type": case["type"],
        "split": case["split"],
        "registry": case["registry"],
        "relevant": relevant,
        "sent_tools": sent_tools,
        "selection_mode": selection_mode,
        "retrievable": retrievable,
        "turns": [
            {"calls": t.calls, "text": t.text[:400], "latency_s": t.latency_s, "ttft_s": t.ttft_s, "stop_reason": t.stop_reason}
            for t in turns
        ],
        "first_tool": first_turn[0]["name"] if first_turn else None,
        "success_at_1": bool(s1),
        "success_at_k": bool(sk),
        "success_at_k_valid": bool(sk_valid),
        "turns_used": len(turns),
        "stop": ep.stop,
        "relevant_called_frac": (len(set(called) & rel) / len(rel)) if (rel and not is_none) else None,
        "calls_total": len(all_calls),
        "calls_args_valid": sum(1 for c in all_calls if c["args_valid"]),
        "not_offered_call": any(not c["offered"] for c in all_calls),
        "text_tool_call_leak": (not first_turn) and bool(_TEXT_TOOL_CALL.search(first_text)),
        "latency_first_s": turns[0].latency_s if turns else None,
        "latency_total_s": sum(t.latency_s or 0 for t in turns) if turns else None,
        "error": ep.error,
    })


def _validate_args(registry: Any, call: dict) -> tuple[bool, str | None]:
    """운영 _execute_tool_call과 같은 기준: 등록된 도구여야 하고 input_model.model_validate를 통과해야 합니다."""
    if "_parse_error" in call["input"]:
        return False, f"invalid JSON: {call['input'].get('_parse_error')}"
    tool = registry.get(call["name"])
    if tool is None:
        return False, "unknown tool"
    try:
        tool.input_model.model_validate(call["input"])
    except Exception as exc:  # noqa: BLE001 - pydantic ValidationError 등 모든 검증 실패
        return False, str(exc).splitlines()[0][:300]
    return True, None
