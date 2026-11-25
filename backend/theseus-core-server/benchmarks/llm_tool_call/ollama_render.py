"""Ollama(0.40.x)가 OpenAI 호환 요청을 모델 프롬프트로 바꾸는 방식을 재현합니다(학습·서빙 렌더링 일치용).

Ollama는 /v1/chat/completions 요청을 Go 구조체(api.Tool, api.Message)로 읽은 뒤 내장 llama-server에 넘기고,
llama-server가 GGUF의 chat template으로 렌더링합니다. 이때 도구 스키마는 Go 구조체에 있는 필드만 남습니다
(api/types.go v0.40.16: ToolProperty = anyOf, type, items, description, enum, properties, required).
default, minimum, maximum, title, additionalProperties 같은 키는 사라지고, parameters의 키 순서도 바뀝니다.
그래서 학습 데이터는 OpenAI 형식 그대로가 아니라 이 축약 스키마로 렌더링해야 운영에서 모델이 보는 것과 같아집니다.

검증: 운영 요청 3건을 디버그 Ollama에 보낸 prompt_tokens와, 이 모듈로 축약한 요청을 llama.cpp(b12655)
/apply-template로 렌더링한 토큰 수가 같은지 확인했습니다(README "학습 데이터 렌더링").
"""

from __future__ import annotations

import json
from typing import Any


def _prop(p: Any) -> Any:
    """api.ToolProperty: 필드 순서와 omitempty를 Go 구조체대로."""
    if not isinstance(p, dict):
        return p
    out: dict[str, Any] = {}
    if p.get("anyOf"):
        out["anyOf"] = [_prop(x) for x in p["anyOf"]]
    t = p.get("type")
    if t:
        out["type"] = t[0] if isinstance(t, list) and len(t) == 1 else t
    if p.get("items") is not None:
        out["items"] = p["items"]  # any: 원본 JSON 그대로
    if p.get("description"):
        out["description"] = p["description"]
    if p.get("enum"):
        out["enum"] = p["enum"]
    if p.get("properties") is not None:
        out["properties"] = {k: _prop(v) for k, v in p["properties"].items()}
    if p.get("required"):
        out["required"] = p["required"]
    return out


def reduce_tool(tool: dict) -> dict:
    """OpenAI 형식 도구 하나를 Ollama api.Tool을 거친 모습으로."""
    fn = tool.get("function", {})
    params = fn.get("parameters") or {}
    rp: dict[str, Any] = {"type": params.get("type", "")}
    if params.get("$defs") is not None:
        rp["$defs"] = params["$defs"]
    if params.get("items") is not None:
        rp["items"] = params["items"]
    if params.get("required"):
        rp["required"] = params["required"]
    props = params.get("properties")
    rp["properties"] = {k: _prop(v) for k, v in props.items()} if props is not None else None
    rf: dict[str, Any] = {"name": fn.get("name", "")}
    if fn.get("description"):
        rf["description"] = fn["description"]
    rf["parameters"] = rp
    out: dict[str, Any] = {"type": tool.get("type", "function")}
    if tool.get("items") is not None:
        out["items"] = tool["items"]
    out["function"] = rf
    return out


def reduce_messages(messages: list[dict]) -> list[dict]:
    """api.Message: 도구 호출 인자는 문자열이 아니라 (순서를 지킨) 객체로 넘어갑니다."""
    out = []
    for m in messages:
        m = dict(m)
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = dict(tc.get("function", {}))
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args) if args.strip() else {}
                    except json.JSONDecodeError:
                        fn["arguments"] = {}
                calls.append({**tc, "function": fn})
            m["tool_calls"] = calls
        out.append(m)
    return out


def reduce_request(messages: list[dict], tools: list[dict]) -> tuple[list[dict], list[dict]]:
    return reduce_messages(messages), [reduce_tool(t) for t in tools]
