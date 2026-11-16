"""도구 → 검색용 텍스트 레시피.

임베딩 프리픽스('passage: ')는 붙이지 않습니다. 프리픽스는 모델마다 달라서 Embedder가 embedder.json 값으로 붙입니다.

* ``passage_body``: 순위용 dense passage.
  "{name} ({name 단어}): {description} 입력: {파라미터 이름}. 한국어: {용어집 표기} {few-shot, 쉼표 구분}"
  (Combine 단계 최종 레시피 'pbest'. few-shot 라벨 '예시 질문:'은 없앴습니다.)
* ``anchor_body``: none 판정용 앵커. 현행(v1) concat 레시피 "{name}: {description} 예시 질문: …".
  보정 계수가 이 분포에 맞춰져 있으므로 피드백 few-shot은 넣지 않습니다.
* ``bm25_document``: name×3 + (description + 용어집 표기) + 파라미터 이름·설명 + few-shot.
* ``coverage_document``: none 판정 커버리지 어휘(앵커 텍스트 + 입력 스키마 JSON).
* ``schema_cost_chars``: LLM에 보내는 스키마 비용 프록시(압축 JSON 글자 수 / 4). tiktoken 불필요.

RECIPE_VERSION은 위 레시피가 바뀌면 올립니다(인덱스 fingerprint에 들어가 재인덱싱을 일으킵니다).
"""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from theseus_engine.core.tool_rag.lexical import bm25_tokens
from theseus_engine.core.tool_rag.tool_gloss import korean_gloss

RECIPE_VERSION = "v2.1"


def split_name(name: str) -> str:
    return re.sub(r"[_\-]+", " ", name or "").strip()


def tool_input_schema(tool: Any) -> dict:
    try:
        schema = tool.to_api_schema().get("input_schema") or {}
    except Exception:
        return {}
    return schema if isinstance(schema, dict) else {}


def _properties(schema: dict) -> dict:
    props = schema.get("properties") or {}
    return props if isinstance(props, dict) else {}


def param_names(schema: dict) -> str:
    return ", ".join(split_name(k) for k in _properties(schema))


def passage_body(tool: Any, examples: Sequence[str], schema: dict) -> str:
    body = f"{tool.name} ({split_name(tool.name)}): {tool.description}"
    params = param_names(schema)
    if params:
        body += f" 입력: {params}."
    gloss = korean_gloss(tool.name, tool.description)
    if gloss:
        body += f" 한국어: {gloss}"
    if examples:
        body += " " + ", ".join(examples)
    return body


def anchor_body(tool: Any, static_examples: Sequence[str]) -> str:
    suffix = (" 예시 질문: " + ", ".join(static_examples)) if static_examples else ""
    return f"{tool.name}: {tool.description}{suffix}"


def bm25_document(tool: Any, examples: Sequence[str], schema: dict) -> list[str]:
    params = " ".join(
        f"{k.replace('_', ' ')} {((v or {}).get('description', '') if isinstance(v, dict) else '') or ''}"
        for k, v in _properties(schema).items()
    )
    desc = (tool.description or "") + " " + korean_gloss(tool.name, tool.description)
    return (
        bm25_tokens(tool.name.replace("_", " ")) * 3
        + bm25_tokens(desc)
        + bm25_tokens(params)
        + bm25_tokens(" ".join(examples))
    )


def coverage_document(tool: Any, static_examples: Sequence[str], schema: dict) -> str:
    return "passage: " + anchor_body(tool, static_examples) + " " + json.dumps(schema, ensure_ascii=False)


def schema_json(tool: Any) -> str:
    try:
        return json.dumps(tool.to_api_schema(), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return json.dumps({"name": getattr(tool, "name", "")}, ensure_ascii=False)


def schema_cost_chars(tool: Any) -> float:
    return len(schema_json(tool)) / 4.0
