"""어휘 신호: BM25 순위 보정과 질의 커버리지(none 판정 특징).

순수 파이썬과 numpy만 씁니다(형태소 분석기, rank_bm25 불필요).

* ``bm25_tokens``: 한글 연속 구간은 음절 bigram, 라틴 문자는 camelCase/snake_case로 나눈 뒤 소문자화,
  경량 접미사 stem, 영어 불용어 제거. 한국어 조사·어미가 붙어도 bigram이 겹치므로 형태소 분석 없이 매칭됩니다.
* ``BM25``: k1=1.2, b=0.75. 도구 수십 개 규모라 역색인 없이 문서별 Counter로 충분합니다.
* ``coverage_tokens``: 질의 토큰(영단어 2자 이상 + 한글 bigram + snake 부분어) 중 도구 카탈로그 어휘에 있는 비율을
  none 판정에 씁니다. 구글 캘린더·카카오톡처럼 카탈로그에 없는 서비스를 요청하면 커버리지가 낮아집니다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, Mapping, Sequence

import numpy as np

_RUN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_HANGUL_RE = re.compile(r"[가-힣]")

EN_STOPWORDS = frozenset(
    "a an the to of in on for and or is are be been it its this that these those with by as at from "
    "use used using can will you your we our us me my i do does did not no if then than so into "
    "only when which what who how all any each just also please".split()
)

# (접미사, 대체, 최소 길이). 앞에서부터 처음 맞는 규칙 하나만 적용합니다.
_STEM_RULES = (
    ("ies", "y", 5),
    ("sses", "ss", 5),
    ("ing", "", 6),
    ("ed", "", 5),
    ("es", "", 5),
    ("s", "", 4),
)


def stem(word: str) -> str:
    """영어 경량 stem(files→file, searching→search). 3자 이하와 숫자는 그대로 둡니다."""
    if len(word) <= 3 or word.isdigit():
        return word
    for suffix, replacement, min_len in _STEM_RULES:
        if word.endswith(suffix) and len(word) >= min_len and not word.endswith("ss"):
            return word[: len(word) - len(suffix)] + replacement
    return word


def bm25_tokens(text: str, *, apply_stem: bool = True) -> list[str]:
    """BM25용 토큰 목록(중복 유지)."""
    out: list[str] = []
    for match in _RUN_RE.finditer(text or ""):
        run = match.group(0)
        if _HANGUL_RE.match(run):
            if len(run) < 2:
                out.append(run)
            else:
                out.extend(run[i : i + 2] for i in range(len(run) - 1))
            continue
        for part in _CAMEL_RE.findall(run):
            part = part.lower()
            if part in EN_STOPWORDS or (len(part) == 1 and not part.isdigit()):
                continue
            out.append(stem(part) if apply_stem else part)
    return out


class BM25:
    """Okapi BM25. 문서 토큰 목록을 받아 질의 토큰에 대한 문서별 점수를 돌려줍니다."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.n_docs = len(docs)
        self._tf = [Counter(doc) for doc in docs]
        doc_len = np.array([len(doc) for doc in docs], dtype=float)
        avgdl = float(doc_len.mean()) if self.n_docs else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        self.idf = {t: math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self._norm = self.k1 * (1 - self.b + self.b * doc_len / (avgdl or 1.0))

    def scores(
        self, query_tokens: Iterable[str], query_weights: Mapping[str, float] | None = None
    ) -> np.ndarray:
        out = np.zeros(self.n_docs)
        qtf: Counter = Counter(query_tokens)
        for token, weight in (query_weights or {}).items():
            qtf[token] = qtf.get(token, 0) + weight
        for token, count in qtf.items():
            idf = self.idf.get(token)
            if idf is None:
                continue
            for i, tf in enumerate(self._tf):
                f = tf.get(token)
                if f:
                    out[i] += count * idf * f * (self.k1 + 1) / (f + self._norm[i])
        return out

    def normalized_scores(self, query: str) -> np.ndarray:
        """점수를 질의별 최댓값으로 나눈 [0, 1] 값. 겹치는 토큰이 없으면 0 벡터."""
        raw = self.scores(bm25_tokens(query))
        top = float(raw.max()) if raw.size else 0.0
        return raw / top if top > 0 else np.zeros_like(raw)


_COV_WORD_RE = re.compile(r"[a-z0-9_]{2,}")
_COV_HANGUL_RE = re.compile(r"[가-힣]+")


def coverage_tokens(text: str) -> list[str]:
    """커버리지용 토큰: 영숫자 단어(2자 이상), 한글 음절 bigram, snake_case 부분어."""
    lowered = (text or "").lower()
    tokens = _COV_WORD_RE.findall(lowered)
    for run in _COV_HANGUL_RE.findall(lowered):
        tokens.extend([run] if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)])
    tokens.extend(p for w in list(tokens) if "_" in w for p in w.split("_") if len(p) >= 2)
    return tokens


def coverage(query: str, vocab: set[str] | frozenset[str]) -> float:
    """질의 토큰 중 카탈로그 어휘에 있는 비율. 토큰이 없으면 1.0(판단 보류)."""
    tokens = coverage_tokens(query)
    if not tokens:
        return 1.0
    return sum(t in vocab for t in tokens) / len(tokens)
