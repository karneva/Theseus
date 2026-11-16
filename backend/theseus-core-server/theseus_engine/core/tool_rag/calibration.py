"""none 판정 보정값 로더.

none 판정은 기본으로 꺼져 있고(THESEUS_TOOL_RAG_NONE_MODE=off), soft로 켤 때만 이 보정값을 읽습니다.
보정 파일(JSON)은 benchmarks/tool_rag/calibrate.py가 평가셋 dev core + calibration_set core로 만듭니다. 형식:

    {
      "embedder_fingerprint": "onnx:<model sha256>:spm:512:mean",
      "recipe_version": "v2.3",
      "none_rule": {"w_top1": ..., "w_cov": ..., "b": ...},
      "fit": {...}            # 적합 메타(데이터·해시, 방법, 합친 CV, 두 세트 사이 전이 추정, 기본값 결정, 날짜)
    }

찾는 순서: THESEUS_TOOL_RAG_CALIBRATION_FILE → <모델 디렉터리>/toolrag_calibration.json → 패키지 동봉 파일(data/).
embedder fingerprint나 레시피 버전이 다르면 경고를 남기고 None을 돌려줍니다(호출자는 none 판정을 끕니다).
절대 코사인 임계값은 모델·양자화·passage 레시피에 묶여 있어서, 다른 모델 점수에 옛 계수를 쓰면 안 됩니다.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from theseus_engine.core.tool_rag.selector import NoneRule
from theseus_engine.core.tool_rag.text import RECIPE_VERSION

log = logging.getLogger(__name__)

CALIBRATION_FILE = "toolrag_calibration.json"
PACKAGED_DIR = Path(__file__).resolve().parent / "data"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("[ToolRAG] 보정 파일을 읽지 못했습니다(%s): %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _candidates(explicit: str | None, model_dir: str | None) -> list[Path]:
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    if model_dir:
        paths.append(Path(model_dir) / CALIBRATION_FILE)
    if PACKAGED_DIR.is_dir():
        paths.extend(sorted(PACKAGED_DIR.glob("toolrag_calibration*.json")))
    return paths


@lru_cache(maxsize=16)
def load_none_rule(embedder_fingerprint: str, explicit: str | None, model_dir: str | None) -> NoneRule | None:
    mismatched: list[str] = []
    for path in _candidates(explicit, model_dir):
        if not path.is_file():
            continue
        data = _read(path)
        if not data:
            continue
        if data.get("embedder_fingerprint") != embedder_fingerprint or data.get("recipe_version") != RECIPE_VERSION:
            mismatched.append(f"{path.name}({data.get('embedder_fingerprint')}, {data.get('recipe_version')})")
            continue
        rule = data.get("none_rule") or {}
        try:
            return NoneRule(float(rule["w_top1"]), float(rule["w_cov"]), float(rule["b"]))
        except (KeyError, TypeError, ValueError):
            log.warning("[ToolRAG] 보정 파일 형식 오류: %s", path)
    log.warning(
        "[ToolRAG] 현재 임베더(%s, 레시피 %s)에 맞는 none 보정값이 없어 none 판정을 끕니다. 확인한 파일: %s",
        embedder_fingerprint,
        RECIPE_VERSION,
        ", ".join(mismatched) or "없음",
    )
    return None
