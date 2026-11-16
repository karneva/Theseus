"""Tool RAG 평가 하네스.

동결 베이스라인 벤치마크(bench.py)의 지표 정의를 그대로 옮겨, 어떤 검색기(Retriever)든
같은 평가셋·같은 정의로 비교할 수 있게 합니다.

사용 예 (저장소 밖 스크래치 폴더에서도 동일):

    import sys
    sys.path.insert(0, r"c:\\DEV\\Theseus\\backend\\theseus-core-server")
    from benchmarks.tool_rag import harness

    class MyRetriever:
        name = "my-variant"
        def index(self, registry): ...
        def rank(self, query): return [("web_search", 0.91), ...]

    metrics = harness.evaluate(MyRetriever(), split="dev")

평가 프로토콜: 기법 선택·튜닝은 dev 분할만 사용합니다. test 분할은 최종 구성과 베이스라인에 대해
한 번만 평가합니다. eval_set.jsonl 라벨은 수정하지 않습니다(load_eval_set이 해시로 검증).
"""

from __future__ import annotations

from . import _env  # noqa: F401  # 반드시 theseus_engine보다 먼저

import gc
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

import numpy as np

HERE = Path(__file__).resolve().parent
EVAL_SET_PATH = HERE / "eval_set.jsonl"
# LF 정규화한 eval_set.jsonl의 sha256 (동결 원본과 동일). 라벨이 바뀌면 평가를 거부합니다.
EVAL_SET_SHA256 = "7777d3b30a5b64111dc2d6a3d5efeeb6122ac7d4b8cfe3778347285df7f35713"

# 지표 정의에 쓰는 필수 도구 집합. 동결 베이스라인 측정 시점의 ESSENTIAL_TOOL_NAMES로 고정합니다.
# (저장소의 ESSENTIAL_TOOL_NAMES를 바꾸는 변형이 나와도 "유사도 슬롯" 지표의 정의는 바뀌지 않아야 함)
FROZEN_ESSENTIALS: frozenset[str] = frozenset(
    {"ask_user", "bash", "create_tool", "edit_file", "glob", "grep", "read_file", "write_file"}
)
KS = (3, 5, 8)
DEFAULT_SELECT_K = 8  # select()가 없는 검색기의 전달 집합 = 필수 도구 ∪ 유사도 상위 8
SPLITS = ("dev", "test", "all")
REGISTRY_KINDS = ("core", "server", "server-default")
# 실제 서버 기본값(THESEUS_ENABLE_ENGINE_RAG_TOOLS=false)이 가시성에서 빼는 엔진 RAG 도구(src/builder/engine.py)
SERVER_DEFAULT_DISABLED: frozenset[str] = frozenset({"search_knowledge_base", "ingest_document"})

_ENC = None


# ───────────────────────────── 검색기 프로토콜 ─────────────────────────────
@runtime_checkable
class Retriever(Protocol):
    """평가 대상 검색기.

    필수:
        name: str                         결과에 기록되는 변형 이름
        rank(query) -> list[(tool, score)] 레지스트리 전체(또는 일부)에 대한 내림차순 순위.
                                           필수 도구를 포함해도 되고 빼도 됩니다(지표 계산 시 제외).
    선택(있으면 하네스가 호출):
        load()                 모델 로드 등 콜드 스타트 작업. 시간과 RSS 증가량을 잽니다.
        index(registry)        평가 레지스트리를 받아 인덱스를 만듭니다. 시간을 잽니다.
        select(query) -> list[str]
                               실제로 LLM에 보낼 도구 집합(가시성 필터 적용 전).
                               없으면 FROZEN_ESSENTIALS ∪ rank 상위 8(필수 제외)로 간주합니다.
        decide_none(query) -> bool
                               "맞는 도구가 없다"는 판정. 없으면 select 결과에 필수 외 도구가
                               하나도 없을 때(= engine_builder의 rag_failed) none으로 봅니다.
        clear_cache()          지연 측정 직전마다 호출(쿼리 임베딩 캐시 비우기 등).
        meta() -> dict         결과 meta에 그대로 기록됩니다.
        uses_torch: bool       True면 torch 시드·스레드 수를 고정한 뒤 RSS 기준점을 잡습니다
                               (동결 베이스라인과 같은 순서).
    """

    name: str

    def rank(self, query: str) -> list[tuple[str, float]]: ...


# ───────────────────────────── 레지스트리 ─────────────────────────────
def _remote_config(allow_write: bool):
    from src.remote_workspace.schemas import RemoteWorkspaceConnectionConfig

    # 연결하지 않는 더미 설정 (tests/test_remote_workspace_core_only.py와 같은 형태)
    return RemoteWorkspaceConnectionConfig.model_validate(
        {
            "remoteWorkspaceId": 1,
            "projectId": 10,
            "host": "example.internal",
            "port": 22,
            "username": "bench",
            "password": "unused",
            "basePath": "/srv/app",
            "allowWriteExecution": allow_write,
            "status": "ACTIVE",
        }
    )


def build_registry(kind: str = "core", *, legacy_demo_tools: bool = False):
    """평가 레지스트리를 실제 조립 코드 경로 그대로 만듭니다.

    core   : ALL_CORE_TOOLS (CLI/TUI/runner setup_engine, Remote Workspace 없는 서버). 헤드라인.
    server : 서버 get_query_engine + Remote Workspace(allowWriteExecution=true)
             = ALL_CORE_TOOLS + remote_* 읽기/쓰기 도구. 가시성은 CLI AGENT 정책이라 엔진 RAG 도구 2개가 보입니다.
    server-default : server와 같은 레지스트리에 실제 서버 기본 가시성(엔진 RAG 도구 2개 숨김)을 적용합니다.
             정답에 그 도구가 있는 질의는 어떤 변형도 전달할 수 없으므로 set_recall 상한이 1보다 낮습니다.
    legacy_demo_tools=True: 동결 베이스라인(2026-11-15 측정) 당시처럼 데모 도구 dummy_echo,
             system_reboot를 맨 앞에 다시 넣습니다. 4a2d1f0에서 ALL_CORE_TOOLS에서 빠졌으며
             동결 결과를 그대로 재현할 때만 씁니다.
    """
    from theseus_engine.tools.core import ALL_CORE_TOOLS
    from theseus_engine.tools.core.base_tools import ToolRegistry

    if kind not in REGISTRY_KINDS:
        raise ValueError(f"registry kind must be one of {REGISTRY_KINDS}, got {kind!r}")
    reg = ToolRegistry()
    if legacy_demo_tools:
        tests_dir = str(_env.SERVER_DIR / "tests")
        if tests_dir not in sys.path:
            sys.path.insert(0, tests_dir)
        from fixtures.demo_tools import DummyTool, SystemRebootTool

        reg.register(DummyTool())
        reg.register(SystemRebootTool())
    for tool_cls in ALL_CORE_TOOLS:
        reg.register(tool_cls())
    reg.bench_kind = kind  # _visibility_policy가 읽습니다(server-default)
    if kind in ("server", "server-default"):
        from src.remote_workspace.read_primitives import build_remote_read_analysis_tools
        from src.remote_workspace.write_primitives import build_remote_write_execution_tools

        cfg = _remote_config(allow_write=True)
        for tool in build_remote_read_analysis_tools(cfg):
            reg.register(tool)
        for tool in build_remote_write_execution_tools(cfg, include_command=cfg.allow_write_execution):
            reg.register(tool)
    return reg


# ───────────────────────────── 평가셋 ─────────────────────────────
def load_eval_set(split: str = "all", registry: str = "core", verify: bool = True) -> list[dict]:
    """평가셋을 읽어 분할·레지스트리로 거릅니다.

    registry='core'이면 registry=="core" 항목만, 'server'·'server-default'이면 전체 항목을 씁니다(동결 벤치와 동일).
    """
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    raw = EVAL_SET_PATH.read_bytes().replace(b"\r\n", b"\n")
    if verify:
        digest = hashlib.sha256(raw).hexdigest()
        if digest != EVAL_SET_SHA256:
            raise RuntimeError(f"eval_set.jsonl이 동결본과 다릅니다 (sha256 {digest}). 라벨은 수정하지 않습니다.")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if registry == "core":
        rows = [r for r in rows if r["registry"] == "core"]
    if split != "all":
        rows = [r for r in rows if r["split"] == split]
    return rows


# ───────────────────────────── 지표 (bench.py와 동일 정의) ─────────────────────────────
def _pctl(a, p):
    return float(np.percentile(np.asarray(a, dtype=float), p)) if len(a) else None


def _dist(a):
    if not len(a):
        return None
    arr = np.asarray(a, dtype=float)
    return {
        "n": int(arr.size),
        "min": float(arr.min()),
        "p5": _pctl(arr, 5),
        "p50": _pctl(arr, 50),
        "mean": float(arr.mean()),
        "p95": _pctl(arr, 95),
        "max": float(arr.max()),
    }


def _mean(a):
    return float(statistics.fmean(a)) if a else None


def recall_at(pred, gold, k):
    return len(set(pred[:k]) & set(gold)) / len(gold)


def ndcg_at(pred, gold, k):
    """정답 순서로 등급을 매김: rel(gold[i]) = 1/(i+1). log2 할인."""
    rel = {g: 1.0 / (i + 1) for i, g in enumerate(gold)}
    dcg = sum(rel.get(p, 0.0) / math.log2(j + 2) for j, p in enumerate(pred[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum(r / math.log2(j + 2) for j, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(pred, gold):
    for j, p in enumerate(pred):
        if p in gold:
            return 1.0 / (j + 1)
    return 0.0


def metric_block(recs, key_pred="pred_sim", key_gold="gold_ne"):
    out: dict[str, Any] = {"n": len(recs)}
    if not recs:
        return out
    for k in KS:
        out[f"recall@{k}"] = _mean([recall_at(r[key_pred], r[key_gold], k) for r in recs])
        out[f"ndcg@{k}"] = _mean([ndcg_at(r[key_pred], r[key_gold], k) for r in recs])
        out[f"all_gold@{k}"] = _mean([float(set(r[key_gold]) <= set(r[key_pred][:k])) for r in recs])
    out["mrr"] = _mean([mrr(r[key_pred], r[key_gold]) for r in recs])
    out["hit@1"] = _mean([float(bool(r[key_pred]) and r[key_pred][0] in r[key_gold]) for r in recs])
    out["primary@1"] = _mean([float(bool(r[key_pred]) and r[key_pred][0] == r[key_gold][0]) for r in recs])
    return out


def _breakdowns(recs, key_pred="pred_sim", key_gold="gold_ne"):
    res = {"all": metric_block(recs, key_pred, key_gold)}
    for field in ("lang", "type", "split"):
        for v in sorted({r[field] for r in recs}):
            res[f"{field}={v}"] = metric_block([r for r in recs if r[field] == v], key_pred, key_gold)
    res["ambiguous=true"] = metric_block([r for r in recs if r["ambiguous"]], key_pred, key_gold)
    return res


def schema_tokens(tool) -> int:
    """도구 1개의 스키마 토큰 수 (tiktoken cl100k_base 프록시, to_api_schema 압축 JSON)."""
    global _ENC
    if _ENC is None:
        import tiktoken

        _ENC = tiktoken.get_encoding("cl100k_base")
    return len(_ENC.encode(json.dumps(tool.to_api_schema(), ensure_ascii=False, separators=(",", ":"))))


# ───────────────────────────── 전달 집합 (engine_builder와 동일 규칙) ─────────────────────────────
def _visibility_policy(registry):
    from theseus_engine.core.tool_visibility import ToolVisibilityPolicy
    from theseus_engine.models.modes import AgentMode

    # 동결 벤치의 CLI AGENT 모드 정책: user_level=5, 도구별 permission_level 그대로.
    # server-default는 여기에 서버 기본 비활성 도구(엔진 RAG)를 더합니다.
    disabled = SERVER_DEFAULT_DISABLED if getattr(registry, "bench_kind", "core") == "server-default" else frozenset()
    return ToolVisibilityPolicy(
        mode=AgentMode.AGENT,
        user_level=5,
        tool_permissions={t.name: getattr(t, "permission_level", 1) for t in registry.list_tools()},
        disabled_tools=disabled,
    )


def _deliver(selected: list[str], registry, policy) -> tuple[list[str], bool]:
    """선택 집합 → LLM이 실제로 받는 집합. 가시성 필터 후, 유사도 도구가 0개면(rag_failed) tool_search 추가."""
    from theseus_engine.core.tool_visibility import build_visible_registry
    from theseus_engine.tools.core.base_tools import ToolRegistry

    sel_reg = ToolRegistry()
    for n in selected:
        sel_reg.register(registry.get(n))
    visible = [t.name for t in build_visible_registry(sel_reg, policy).list_tools()]
    rag_failed = len(set(selected) - FROZEN_ESSENTIALS) == 0
    if rag_failed and "tool_search" not in visible:
        visible.append("tool_search")
    return visible, rag_failed


def _dedup_known(names: Iterable[str], known: set[str], what: str) -> list[str]:
    out, seen = [], set()
    for n in names:
        if n not in known:
            raise ValueError(f"{what}가 레지스트리에 없는 도구를 반환했습니다: {n!r}")
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ───────────────────────────── 실행 환경 ─────────────────────────────
def _rss_mb():
    try:
        import psutil

        return psutil.Process().memory_info().rss / 2**20
    except Exception:  # psutil 없음
        return None


def _git_commit():
    try:
        out = subprocess.run(
            ["git", "-C", str(_env.SERVER_DIR), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        sha = out.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(_env.SERVER_DIR), "status", "--porcelain", "--", "theseus_engine", "src"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if not sha:
            raise RuntimeError("git 정보 없음")
        return {"commit": sha, "engine_src_dirty": bool(dirty)}
    except Exception:
        # 컨테이너처럼 .git이 없는 곳: 실행자가 소스 커밋과 이미지를 환경변수로 넘깁니다.
        return {
            "commit": os.getenv("THESEUS_BENCH_SOURCE_COMMIT") or None,
            "engine_src_dirty": None,
            "image": os.getenv("THESEUS_BENCH_IMAGE") or None,
        }


def _pin_runtime(retriever, threads: int) -> int | None:
    random.seed(0)
    np.random.seed(0)
    if getattr(retriever, "uses_torch", False):
        import torch

        torch.manual_seed(0)
        torch.set_num_threads(threads)
        return torch.get_num_threads()
    return None


def _versions():
    out = {"numpy": np.__version__}
    for m in ("tiktoken", "torch", "sentence_transformers", "transformers", "onnxruntime"):
        mod = sys.modules.get(m)
        if mod is not None:
            out[m] = getattr(mod, "__version__", "?")
    return out


# ───────────────────────────── 평가 ─────────────────────────────
def evaluate(
    retriever: Retriever,
    split: str = "dev",
    registry: str = "core",
    *,
    latency_passes: int = 3,
    threads: int = 4,
    include_per_item: bool = True,
    legacy_demo_tools: bool = False,
) -> dict[str, Any]:
    """검색기를 동결 평가셋으로 평가해 지표 dict를 돌려줍니다.

    split   : 'dev'(튜닝용) | 'test'(최종 1회) | 'all'
    registry: 'core'(헤드라인) | 'server' | 'server-default'(실제 서버 기본 가시성)
    결과의 "summary"에 주요 지표가 평평하게 정리돼 있습니다.

    legacy_demo_tools: 동결 원본 재현용 (build_registry 참고). 새 변형 비교에는 쓰지 않습니다.

    주의: cold_load_s / rss_delta_mb는 프로세스에서 처음 load()할 때만 의미가 있습니다.
    """
    if not hasattr(retriever, "rank"):
        raise TypeError("retriever는 rank(query)를 구현해야 합니다")
    from theseus_engine.tools.core.tool_search_tool import ToolSearchTool

    rows = load_eval_set(split, registry)
    reg = build_registry(registry, legacy_demo_tools=legacy_demo_tools)
    names_in_reg = {t.name for t in reg.list_tools()}
    tool_tok = {t.name: schema_tokens(t) for t in reg.list_tools()}
    tool_tok.setdefault("tool_search", schema_tokens(ToolSearchTool()))
    policy = _visibility_policy(reg)

    # 1) 콜드 로드 (동결 벤치와 같은 순서: torch 고정 → gc → RSS 기준 → load)
    torch_threads = _pin_runtime(retriever, threads)
    gc.collect()
    rss_before = _rss_mb()
    t0 = time.perf_counter()
    if hasattr(retriever, "load"):
        retriever.load()
    cold_load_s = time.perf_counter() - t0
    gc.collect()
    rss_after_load = _rss_mb()

    # 2) 인덱스
    t0 = time.perf_counter()
    if hasattr(retriever, "index"):
        retriever.index(reg)
    index_ms = (time.perf_counter() - t0) * 1000

    # 3) 항목별 예측
    has_select = hasattr(retriever, "select")
    has_none = hasattr(retriever, "decide_none")
    recs = []
    for r in rows:
        q = r["query"]
        ranked = list(retriever.rank(q))
        rank_names = _dedup_known((n for n, _ in ranked), names_in_reg, "rank()")
        score_of: dict[str, float] = {}
        for n, s in ranked:
            score_of.setdefault(n, float(s))
        pred_sim = [n for n in rank_names if n not in FROZEN_ESSENTIALS]
        if has_select:
            selected = _dedup_known(retriever.select(q), names_in_reg, "select()")
        else:
            selected = sorted((FROZEN_ESSENTIALS & names_in_reg) | set(pred_sim[:DEFAULT_SELECT_K]))
        delivered, rag_failed = _deliver(selected, reg, policy)
        none_pred = bool(retriever.decide_none(q)) if has_none else rag_failed
        gold_full = [g for g in r["relevant"] if g in names_in_reg]
        recs.append(
            {
                "id": r["id"],
                "query": q,
                "lang": r["lang"],
                "type": r["type"],
                "split": r["split"],
                "ambiguous": r["ambiguous"],
                "gold_full": gold_full,
                "gold_ne": [g for g in gold_full if g not in FROZEN_ESSENTIALS],
                "pred_sim": pred_sim,
                "scores": score_of,
                "selected": selected,
                "delivered": delivered,
                "rag_failed": rag_failed,
                "none_pred": none_pred,
            }
        )

    answerable = [x for x in recs if x["type"] != "none"]
    nonerecs = [x for x in recs if x["type"] == "none"]
    ne_eval = [x for x in answerable if x["gold_ne"]]  # 유사도 슬롯 평가 대상
    incl_eval = [x for x in answerable if x["gold_full"]]  # 전달 집합 평가 대상

    ranking = _breakdowns(ne_eval)
    ranking["n_answerable_skipped_all_gold_essential"] = len(answerable) - len(ne_eval)

    def _set_recall(key, xs):
        return _mean([len(set(x["gold_full"]) & set(x[key])) / len(x["gold_full"]) for x in xs])

    delivered_block = {
        "definition": "가시성 필터(AGENT, user_level=5) 적용 후 + rag_failed면 tool_search 추가. 정답은 필수 도구 포함 전체 정답",
        "set_recall": _set_recall("delivered", incl_eval),
        "set_recall_before_visibility": _set_recall("selected", incl_eval),
        "all_gold_covered": _mean([float(set(x["gold_full"]) <= set(x["delivered"])) for x in incl_eval]),
        "nonessential_set_recall": _mean(
            [len(set(x["gold_ne"]) & set(x["selected"])) / len(x["gold_ne"]) for x in ne_eval]
        ),
        "set_size": _dist([len(x["delivered"]) for x in recs]),
        "set_recall_by_lang": {
            lang: _set_recall("delivered", [x for x in incl_eval if x["lang"] == lang]) for lang in ("ko", "en")
        },
    }

    tp = sum(1 for x in nonerecs if x["none_pred"])
    fn = len(nonerecs) - tp
    fp = sum(1 for x in answerable if x["none_pred"])
    tn = len(answerable) - fp
    prec = tp / (tp + fp) if (tp + fp) else 0.0  # 예측 0건이면 0 (zero_division=0)
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    none_block = {
        "definition": "양성 = 정답 type이 none인 질의. 예측 = decide_none(q), 없으면 rag_failed(유사도 도구 0개)",
        "source": "decide_none" if has_none else "rag_failed",
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": prec,
        "recall": rec,
        "f1": (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0,
        "false_trigger_rate_answerable": fp / len(answerable) if answerable else None,
        "rag_failed_rate_all": _mean([float(x["rag_failed"]) for x in recs]),
    }

    tok_delivered = [sum(tool_tok[n] for n in x["delivered"]) for x in recs]
    tokens_block = {
        "note": "tiktoken cl100k_base 프록시, 도구별 to_api_schema 압축 JSON 합",
        "all_tools": sum(tool_tok[n] for n in names_in_reg),
        "essentials_only": sum(tool_tok[n] for n in FROZEN_ESSENTIALS if n in tool_tok),
        "delivered": _dist(tok_delivered),
        "selected": _dist([sum(tool_tok[n] for n in x["selected"]) for x in recs]),
    }
    tokens_block["delivered_mean_saving_vs_all"] = (
        1 - tokens_block["delivered"]["mean"] / tokens_block["all_tools"] if recs else None
    )

    # 4) 웜 지연 (select 우선, 없으면 rank). 호출마다 clear_cache()로 쿼리 캐시를 비움.
    lat = []
    timed = retriever.select if has_select else retriever.rank
    for _ in range(max(0, latency_passes)):
        for r in rows:
            if hasattr(retriever, "clear_cache"):
                retriever.clear_cache()
            t0 = time.perf_counter()
            timed(r["query"])
            lat.append((time.perf_counter() - t0) * 1000)
    gc.collect()
    rss_after_eval = _rss_mb()

    resources = {
        "cold_load_s": cold_load_s,
        "index_build_ms": index_ms,
        "rss_before_load_mb": rss_before,
        "rss_after_load_mb": rss_after_load,
        "rss_delta_mb": (rss_after_load - rss_before) if rss_before is not None else None,
        "rss_after_eval_mb": rss_after_eval,
        "torch_threads": torch_threads,
    }
    latency_block = {
        "timed_call": "select" if has_select else "rank",
        "passes": latency_passes,
        "warm_query_ms": _dist(lat),
    }

    allm = ranking["all"]
    lat_d = latency_block["warm_query_ms"] or {}
    summary = {
        "variant": getattr(retriever, "name", type(retriever).__name__),
        "split": split,
        "registry": registry,
        "n_ranking": allm["n"],
        "r3": allm.get("recall@3"),
        "r5": allm.get("recall@5"),
        "r8": allm.get("recall@8"),
        "ndcg5": allm.get("ndcg@5"),
        "mrr": allm.get("mrr"),
        "hit1": allm.get("hit@1"),
        "r3_ko": ranking.get("lang=ko", {}).get("recall@3"),
        "r3_en": ranking.get("lang=en", {}).get("recall@3"),
        "none_precision": none_block["precision"],
        "none_recall": none_block["recall"],
        "none_f1": none_block["f1"],
        "set_recall_delivered": delivered_block["set_recall"],
        "avg_selected_schema_tokens": tokens_block["delivered"]["mean"] if recs else None,
        "p95_selected_schema_tokens": tokens_block["delivered"]["p95"] if recs else None,
        "warm_p50_ms": lat_d.get("p50"),
        "warm_p95_ms": lat_d.get("p95"),
        "cold_load_s": cold_load_s,
        "rss_delta_mb": resources["rss_delta_mb"],
    }

    try:
        from theseus_engine.core.tool_retriever import ESSENTIAL_TOOL_NAMES

        repo_ess_same = set(ESSENTIAL_TOOL_NAMES) == set(FROZEN_ESSENTIALS)
    except Exception:
        repo_ess_same = None

    result: dict[str, Any] = {
        "summary": summary,
        "meta": {
            "variant": summary["variant"],
            "retriever_meta": retriever.meta() if hasattr(retriever, "meta") else {},
            "split": split,
            "registry": registry,
            "n_items": len(recs),
            "n_answerable": len(answerable),
            "n_none": len(nonerecs),
            "n_tools": len(names_in_reg),
            "legacy_demo_tools": legacy_demo_tools,
            "eval_set_sha256": EVAL_SET_SHA256,
            "frozen_essentials": sorted(FROZEN_ESSENTIALS),
            "repo_essentials_equal_frozen": repo_ess_same,
            "ks": list(KS),
            "has_select": has_select,
            "has_decide_none": has_none,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "versions": _versions(),
            "feedback_log": "disabled (THESEUS_DATA_DIR -> 빈 임시 디렉터리)",
            "hf_offline": os.environ.get("HF_HUB_OFFLINE"),
            **_git_commit(),
        },
        "ranking_sim_slots_excl_essentials": ranking,
        "delivered_set": delivered_block,
        "none_detection": none_block,
        "prompt_tokens_cl100k": tokens_block,
        "latency": latency_block,
        "resources": resources,
        "hubness_top3_counts": dict(Counter(n for x in recs for n in x["pred_sim"][:3]).most_common(12)),
    }
    if include_per_item:
        result["per_item"] = [
            {
                "id": x["id"],
                "lang": x["lang"],
                "type": x["type"],
                "split": x["split"],
                "gold_full": x["gold_full"],
                "gold_ne": x["gold_ne"],
                "pred_sim_top8": [[n, round(x["scores"].get(n, float("nan")), 4)] for n in x["pred_sim"][:8]],
                "delivered": x["delivered"],
                "rag_failed": x["rag_failed"],
                "none_pred": x["none_pred"],
            }
            for x in recs
        ]
    return result


def format_summary(result: dict[str, Any]) -> str:
    """사람이 읽는 한 블록 요약."""
    s = result["summary"]

    def f(v, nd=3):
        return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))

    return (
        f"[{s['variant']}] split={s['split']} registry={s['registry']} n={s['n_ranking']}\n"
        f"  R@3 {f(s['r3'])} (KO {f(s['r3_ko'])} / EN {f(s['r3_en'])})  R@5 {f(s['r5'])}  R@8 {f(s['r8'])}"
        f"  nDCG@5 {f(s['ndcg5'])}  MRR {f(s['mrr'])}  Hit@1 {f(s['hit1'])}\n"
        f"  none P/R/F1 {f(s['none_precision'])}/{f(s['none_recall'])}/{f(s['none_f1'])}"
        f"  set_recall_delivered {f(s['set_recall_delivered'])}\n"
        f"  schema tokens avg {f(s['avg_selected_schema_tokens'], 1)} / p95 {f(s['p95_selected_schema_tokens'], 1)}"
        f"  warm p50 {f(s['warm_p50_ms'], 1)} ms / p95 {f(s['warm_p95_ms'], 1)} ms"
        f"  cold {f(s['cold_load_s'], 1)} s  RSS +{f(s['rss_delta_mb'], 0)} MB"
    )
