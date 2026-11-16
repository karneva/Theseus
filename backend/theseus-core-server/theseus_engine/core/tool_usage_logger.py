"""Tool 사용 피드백 로거.

CLI에서 실제로 쓰인 도구를 (사용자 질의, 도구) 쌍으로 모아 Tool RAG few-shot을 보강합니다.
로그는 ``$THESEUS_DATA_DIR/tool_usage.jsonl``(기본 ~/.theseus)에 JSONL로 쌓입니다.

v1은 ToolExecutionStarted마다 무조건 기록해서 read_file·bash 같은 필수 도구, 에러 난 호출, 중복 질의가 쌓였고
그 질의가 다시 해당 도구의 few-shot이 되어 허브(아무 질의에나 뜨는 도구)를 키웠습니다. 지금 규칙:

1. 필수 도구와 tool_search는 기록하지 않습니다(검색과 무관하게 항상 보내는 도구).
2. 이번 턴에 검색이 고른 도구만 기록합니다. ``provenance``는 slot(유사도 슬롯) | tool_search | hook(사후 주입).
   provenance가 없으면(히스토리 고정, 폴백 전체 전송 등) 기록하지 않습니다.
3. 성공한 호출만 기록합니다(호출자가 ToolExecutionCompleted에서 is_error가 아닐 때 부릅니다).
4. 질의는 4~200자만 받고, 경로·URL·키처럼 보이는 토큰이 있으면 버립니다(사용자 데이터가 인덱스로 새지 않게).
5. 읽을 때 정규화한 (질의, 도구)로 중복을 지우고 도구당 최신 N개(기본 5)만 씁니다.
6. 파일이 1 MB를 넘으면 ``.1``로 회전합니다.
7. 피드백은 순위용 passage와 BM25 shots에만 섞고, none 판정 앵커에는 섞지 않습니다(보정 분포 고정).
   서버 기본은 off(THESEUS_TOOL_RAG_FEEDBACK)입니다. 멀티테넌트에서 한 사용자의 질의가 다른 프로젝트 인덱스로 새기 때문입니다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from theseus_engine.core.tool_rag.examples import ESSENTIAL_TOOL_NAMES, TOOL_SEARCH_NAME

log = logging.getLogger(__name__)

PROVENANCES = frozenset({"slot", "tool_search", "hook"})
NEVER_LOGGED = frozenset(ESSENTIAL_TOOL_NAMES | {TOOL_SEARCH_NAME, "create_tool"})
MIN_QUERY_CHARS = 4
MAX_QUERY_CHARS = 200
MAX_LOG_BYTES = 1_000_000
DEFAULT_MAX_PER_TOOL = 5

# 경로(/a/b, C:\x), URL, 이메일, 키·토큰처럼 보이는 긴 영숫자 덩어리
_SENSITIVE_RE = re.compile(
    r"(?:[A-Za-z]:\\|(?:^|\s)[~.]?/[\w.\-]+|[\w.\-]+[/\\][\w.\-]+|https?://|[\w.+-]+@[\w-]+\.[\w.]+|"
    r"\b(?:sk|pk|ghp|gho|xox[abp]|AKIA|eyJ)[-_A-Za-z0-9]{8,}|\b[A-Za-z0-9+/_\-]{32,}\b)"
)
_WS_RE = re.compile(r"\s+")


def _log_dir() -> Path:
    return Path(os.getenv("THESEUS_DATA_DIR") or (Path.home() / ".theseus"))


def log_file() -> Path:
    return _log_dir() / "tool_usage.jsonl"


def normalize_query(query: str) -> str:
    return _WS_RE.sub(" ", (query or "").strip())


def accept_record(user_query: str, tool_name: str, provenance: str | None) -> str | None:
    """기록 가능하면 정규화한 질의를, 아니면 None을 돌려줍니다."""
    if not tool_name or tool_name in NEVER_LOGGED:
        return None
    if provenance not in PROVENANCES:
        return None
    query = normalize_query(user_query)
    if not (MIN_QUERY_CHARS <= len(query) <= MAX_QUERY_CHARS):
        return None
    if _SENSITIVE_RE.search(query):
        return None
    return query


_write_lock = threading.Lock()


def _write_record_sync(record: dict) -> None:
    path = log_file()
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size > MAX_LOG_BYTES:
                os.replace(path, path.with_suffix(path.suffix + ".1"))
        except FileNotFoundError:
            pass
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _record(user_query: str, tool_name: str, provenance: str | None) -> dict | None:
    query = accept_record(user_query, tool_name, provenance)
    if query is None:
        return None
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": query,
        "tool": tool_name,
        "provenance": provenance,
    }


def record_tool_call(user_query: str, tool_name: str, *, provenance: str | None) -> bool:
    """성공한 도구 호출을 기록합니다(동기). 기록했으면 True."""
    record = _record(user_query, tool_name, provenance)
    if record is None:
        return False
    try:
        _write_record_sync(record)
    except OSError as exc:
        log.debug("[ToolUsageLogger] 로그 기록 실패: %s", exc)
        return False
    return True


async def record_tool_call_async(user_query: str, tool_name: str, *, provenance: str | None) -> bool:
    """record_tool_call의 비동기 버전(파일 I/O를 스레드로 넘깁니다)."""
    record = _record(user_query, tool_name, provenance)
    if record is None:
        return False
    try:
        await asyncio.to_thread(_write_record_sync, record)
    except OSError as exc:
        log.debug("[ToolUsageLogger] 로그 기록 실패: %s", exc)
        return False
    return True


_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[Dict[str, List[str]], str]] = {}


def load_feedback_queries(max_per_tool: int = DEFAULT_MAX_PER_TOOL) -> tuple[Dict[str, List[str]], str]:
    """(도구별 최신 질의 목록, 버전 문자열). 버전은 파일 크기·수정 시각이라 내용이 바뀌면 인덱스가 다시 만들어집니다."""
    path = log_file()
    try:
        stat = path.stat()
    except OSError:
        return {}, "none"
    version = f"{stat.st_size}:{stat.st_mtime_ns}:{max_per_tool}"
    key = (str(path), version)
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    per_tool: Dict[str, List[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.debug("[ToolUsageLogger] 로그 읽기 실패: %s", exc)
        return {}, "none"
    for line in reversed(lines):  # 최신 우선
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        tool = str(rec.get("tool") or "")
        # 옛 형식(provenance 없음)이나 거부 대상은 읽을 때도 다시 거릅니다.
        query = accept_record(str(rec.get("query") or ""), tool, rec.get("provenance"))
        if query is None:
            continue
        dedup_key = (tool, query.lower())
        if dedup_key in seen or len(per_tool[tool]) >= max_per_tool:
            continue
        seen.add(dedup_key)
        per_tool[tool].append(query)
    result = (dict(per_tool), version)
    with _cache_lock:
        _cache.clear()
        _cache[key] = result
    return result


def get_log_stats() -> Dict[str, int]:
    """도구별 기록 횟수(많은 순)."""
    counts: Dict[str, int] = defaultdict(int)
    path = log_file()
    if not path.exists():
        return {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                tool = json.loads(line).get("tool", "")
            except (json.JSONDecodeError, AttributeError):
                continue
            if tool:
                counts[tool] += 1
    except OSError:
        pass
    return dict(sorted(counts.items(), key=lambda item: -item[1]))
