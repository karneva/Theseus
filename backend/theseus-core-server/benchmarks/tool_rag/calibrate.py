"""none 판정 보정: dev 분할만으로 선형 규칙을 적합해 toolrag_calibration.json을 씁니다.

    python -m benchmarks.tool_rag.calibrate --out theseus_engine/core/tool_rag/data/toolrag_calibration.e5-small-int8.json

절차(Combine 단계와 같음, numpy만 사용):
  1. 특징: top1 = 앵커 passage 원시 코사인 최댓값(tool_search 제외), cov = 질의 커버리지.
  2. class-balanced L2 로지스틱 회귀(Newton, 표준화 공간)를 dev 전체에 적합합니다.
  3. 임계값: dev에서 false-none(답 있는 질의를 none으로 판정한 비율) <= cap(기본 5%) 중 F1이 최대인 값.
  4. 참고용으로 반복 계층 5-fold × 20 CV 추정치(P/R/F1/false-none)를 같이 기록합니다.

test 분할은 읽지 않습니다. 임베딩 모델을 바꾸면(3단계 파인튜닝 등) 새 모델 디렉터리로 이 스크립트를 다시 돌려
보정 파일을 만든 뒤 하네스로 dev와 test를 1회 평가합니다.
"""

from __future__ import annotations

from . import _env  # noqa: F401  # 반드시 theseus_engine보다 먼저

import argparse
import dataclasses
import datetime as dt
import json
from pathlib import Path

import numpy as np

from . import harness


def fit_lr(X: np.ndarray, y: np.ndarray, C: float = 1.0, iters: int = 100) -> tuple[np.ndarray, float]:
    """class_weight=balanced, L2(C) 로지스틱 회귀(표준화 공간, Newton). 원 공간 (w, b)를 돌려줍니다."""
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Z = (X - mu) / sd
    n = len(y)
    pos = y.sum()
    sw = np.where(y == 1, n / (2 * pos), n / (2 * (n - pos)))
    Za = np.hstack([Z, np.ones((n, 1))])
    w = np.zeros(Za.shape[1])
    reg = np.r_[np.ones(Z.shape[1]) / C, 0.0]
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Za @ w))
        g = Za.T @ (sw * (p - y)) + reg * w
        H = (Za * (sw * p * (1 - p))[:, None]).T @ Za + np.diag(reg)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-10:
            break
    wo = w[:-1] / sd
    bo = w[-1] - float((w[:-1] * mu / sd).sum())
    return wo, bo


def choose_threshold(d: np.ndarray, y: np.ndarray, cap: float = 0.05) -> float:
    """결정값 d(클수록 none). false-none <= cap 중 F1 최대(동점이면 fp 적은 쪽)인 임계값 t (d - t >= 0 → none)."""
    best, best_t = (-1.0, 0.0), float(d.max()) + 1
    neg = (y == 0).sum()
    for t in np.unique(d):
        pred = d >= t
        tp = int((pred & (y == 1)).sum())
        fp = int((pred & (y == 0)).sum())
        if fp / max(1, neg) > cap:
            continue
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / max(1, y.sum())
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        if (f1, -fp) > best:
            best, best_t = (f1, -fp), float(t)
    return best_t


def fit_none_rule(top1: np.ndarray, cov: np.ndarray, y: np.ndarray, cap: float = 0.05) -> dict:
    X = np.c_[top1, cov]
    w, b = fit_lr(X, y)
    t = choose_threshold(X @ w + b, y, cap)
    return {"w_top1": float(w[0]), "w_cov": float(w[1]), "b": float(b - t)}


def cv_none(top1, cov, y, cap=0.05, folds=5, reps=20, seed=0) -> dict:
    """반복 계층 k-fold: out-of-fold 예측으로 P/R/F1/false-none을 추정합니다."""
    rng = np.random.default_rng(seed)
    res = []
    for _ in range(reps):
        pred = np.zeros(len(y), bool)
        idx_pos, idx_neg = rng.permutation(np.where(y == 1)[0]), rng.permutation(np.where(y == 0)[0])
        fold_of = np.empty(len(y), int)
        fold_of[idx_pos] = np.arange(len(idx_pos)) % folds
        fold_of[idx_neg] = np.arange(len(idx_neg)) % folds
        for f in range(folds):
            tr, te = fold_of != f, fold_of == f
            r = fit_none_rule(top1[tr], cov[tr], y[tr], cap)
            pred[te] = r["w_top1"] * top1[te] + r["w_cov"] * cov[te] + r["b"] >= 0
        tp = int((pred & (y == 1)).sum())
        fp = int((pred & (y == 0)).sum())
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / y.sum()
        res.append((prec, rec, 2 * prec * rec / (prec + rec) if prec + rec else 0, fp / (y == 0).sum()))
    a = np.array(res)
    return {
        "precision": float(a[:, 0].mean()),
        "recall": float(a[:, 1].mean()),
        "f1": float(a[:, 2].mean()),
        "f1_sd": float(a[:, 2].std()),
        "false_none": float(a[:, 3].mean()),
    }


def main(argv=None) -> int:
    from theseus_engine.config import get_tool_rag_settings
    from theseus_engine.core.tool_rag.cache import EmbeddingCache
    from theseus_engine.core.tool_rag.retriever import ToolRetriever
    from theseus_engine.core.tool_rag.text import RECIPE_VERSION

    ap = argparse.ArgumentParser(prog="python -m benchmarks.tool_rag.calibrate")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--cap", type=float, default=0.05, help="dev false-none 상한")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)

    settings = dataclasses.replace(
        get_tool_rag_settings(), embed_threads=args.threads, feedback="off", cache_dir=None, none_mode="off"
    )
    retr = ToolRetriever(settings=settings, cache=EmbeddingCache(None), none_rule=None)
    index = retr.get_index(harness.build_registry("core"))
    rows = harness.load_eval_set("dev", "core")  # test는 읽지 않습니다.
    y = np.array([int(r["type"] == "none") for r in rows])
    feats = [retr.score(r["query"], index)[1:] for r in rows]
    top1 = np.array([f[0] for f in feats])
    cov = np.array([f[1] for f in feats])

    rule = fit_none_rule(top1, cov, y, cap=args.cap)
    cv = cv_none(top1, cov, y, cap=args.cap)
    pred = rule["w_top1"] * top1 + rule["w_cov"] * cov + rule["b"] >= 0
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    out = {
        "embedder_fingerprint": retr.embedder().fingerprint,
        "recipe_version": RECIPE_VERSION,
        "none_rule": rule,
        "equivalent": f"top1 + {rule['w_cov'] / rule['w_top1']:.4f}*cov < {-rule['b'] / rule['w_top1']:.5f} -> none",
        "fit": {
            "split": "dev",
            "registry": "core",
            "n": int(len(y)),
            "n_none": int(y.sum()),
            "method": "class-balanced L2 logistic regression [top1, cov] + threshold (false-none <= cap, max F1)",
            "cap": args.cap,
            "in_sample": {"tp": tp, "fp": fp, "fn": int(y.sum()) - tp},
            "cv_5fold_x20": cv,
            "eval_set_sha256": harness.EVAL_SET_SHA256,
            "date": dt.date.today().isoformat(),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
