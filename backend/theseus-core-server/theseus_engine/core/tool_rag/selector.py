"""전달 집합 선택 규칙(순수 함수, 모델 불필요).

* 비용 인지 슬롯(``select_slots``): 순위 i(1부터)의 후보는 ``i**alpha * cost(tool) <= budget``일 때 넣습니다.
  1위는 항상 넣고 상위 ``imax``개까지만 봅니다. 순위 사전확률(Zipf, 1/i)을 스키마 비용으로 나눈 값이
  임계 이상인 도구만 보내는 것과 같습니다. 스키마가 큰 도구는 상위에 있을 때만 들어갑니다.
  dev에서 고른 값: alpha=1, budget=700(글자/4 단위), imax=12.
* none 판정(``NoneRule``): 선형 규칙 w_top1*top1 + w_cov*cov + b >= 0이면 "맞는 도구 없음".
* ``assemble``: 필수 → 히스토리 고정 → 슬롯 순서로 합치고, none이면 슬롯을 상위 soft_keep개로 줄이고
  tool_search를 붙입니다(soft fallback). 유사도 슬롯을 비우지 않으므로 오판 비용이 작습니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from theseus_engine.core.tool_rag.examples import TOOL_SEARCH_NAME


@dataclass(frozen=True)
class NoneRule:
    w_top1: float
    w_cov: float
    b: float

    def decision(self, top1: float, cov: float) -> float:
        return self.w_top1 * top1 + self.w_cov * cov + self.b

    def is_none(self, top1: float, cov: float) -> bool:
        return self.decision(top1, cov) >= 0


def decide_none(top1: float, cov: float, rule: NoneRule | None) -> bool:
    return bool(rule is not None and rule.is_none(top1, cov))


def select_slots(
    ranked: Sequence[str],
    costs: Mapping[str, float],
    *,
    budget: float,
    alpha: float = 1.0,
    imax: int = 12,
) -> list[str]:
    """ranked는 이미 후보(보이는 도구 − 필수 − 히스토리)로 걸러진 순위 목록입니다."""
    slots: list[str] = []
    for i, name in enumerate(ranked[: max(0, imax)], 1):
        if i == 1 or (i**alpha) * float(costs.get(name, 0.0)) <= budget:
            slots.append(name)
    return slots


def assemble(
    essentials: Iterable[str],
    history: Iterable[str],
    slots: Sequence[str],
    *,
    is_none: bool,
    soft_keep: int = 3,
    tool_search_visible: bool,
) -> tuple[list[str], list[str]]:
    """(전달할 도구 이름 목록, 최종 슬롯 목록). 중복은 앞의 것을 남깁니다."""
    final_slots = list(slots)
    if is_none and tool_search_visible:
        final_slots = [n for n in final_slots if n != TOOL_SEARCH_NAME][: max(0, soft_keep)]
        final_slots.append(TOOL_SEARCH_NAME)
    out: list[str] = []
    seen: set[str] = set()
    for name in [*essentials, *history, *final_slots]:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out, final_slots
