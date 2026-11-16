"""none 판정 보정: dev core + calibration_set core로 선형 규칙을 적합해 toolrag_calibration.json을 씁니다.

    python -m benchmarks.tool_rag.calibrate --out theseus_engine/core/tool_rag/data/toolrag_calibration.e5-small-int8.json

데이터(test·holdout은 읽지 않습니다):
  * 평가셋 dev 분할 core 질의 107개(none 18개)
  * calibration_set.jsonl core 질의 184개(none 86개). 평가셋·용어집·few-shot을 보지 않은 작성자가 쓴 튜닝용 질의.
    답 있는 질의의 relevant 라벨은 작성자 한 명의 추정이지만 none 판정에는 type(none 여부)만 씁니다.
두 세트를 합친 291개(none 104개)로 적합합니다. 작성자가 다른 두 세트는 none 정의가 달라서(dev는 외부 서비스 위주,
calibration_set은 잡담·일반 지식까지 none) 한쪽에만 맞춘 임계값은 다른 쪽에서 크게 빗나갔습니다.

절차(numpy만 사용):
  1. 특징: top1 = 앵커 passage 원시 코사인 최댓값(tool_search 제외), cov = 질의 커버리지.
  2. class-balanced L2 로지스틱 회귀(Newton, 표준화 공간)를 합친 데이터 전체에 적합합니다.
  3. 임계값: false-none(답 있는 질의를 none으로 판정한 비율) <= cap(기본 5%) 중 F1이 최대인 값.
  4. 기록용 추정치: 합친 데이터의 반복 계층 5-fold × 20 CV, 그리고 두 세트 사이 전이(calibration_set으로 적합 → dev
     평가, dev로 적합 → calibration_set 평가).

런타임 기본값은 none 판정을 끕니다(THESEUS_TOOL_RAG_NONE_MODE=off). 미리 정한 채택 기준(양방향 전이에서 F1 >= 0.5이고
false-none <= 5%)을 이 규칙과 탐색한 대안(특징 추가, 프로토타입 margin)이 모두 넘지 못했기 때문입니다(fit.decision).
이 파일은 THESEUS_TOOL_RAG_NONE_MODE=soft로 켤 때 쓰입니다. 임베딩 모델을 바꾸면(3단계 파인튜닝 등) 새 모델 디렉터리로
이 스크립트를 다시 돌립니다.
"""

from __future__ import annotations

from . import _env  # noqa: F401  # 반드시 theseus_engine보다 먼저

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

from . import harness

CALIBRATION_SET_PATH = harness.HERE / "calibration_set.jsonl"
# LF 정규화한 calibration_set.jsonl의 sha256(0771e25에서 고정). 바뀌면 보정을 거부합니다.
CALIBRATION_SET_SHA256 = "6745784ec5916d936ee4cf96d54e097e634b204d5274de6b989da951d67cb1d3"
TRANSFER_TARGET = {"min_f1": 0.5, "max_false_none": 0.05}


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


def load_calibration_set(registry: str = "core") -> list[dict]:
    raw = CALIBRATION_SET_PATH.read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != CALIBRATION_SET_SHA256:
        raise RuntimeError(f"calibration_set.jsonl이 고정본과 다릅니다(sha256 {digest}).")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return [r for r in rows if r["registry"] == registry] if registry == "core" else rows


def apply_rule(rule: dict, top1: np.ndarray, cov: np.ndarray) -> np.ndarray:
    return rule["w_top1"] * top1 + rule["w_cov"] * cov + rule["b"] >= 0


def confusion(pred: np.ndarray, y: np.ndarray) -> dict:
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int(y.sum()) - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / max(1, int(y.sum()))
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1,
        "false_none": fp / max(1, int((y == 0).sum())),
    }


def transfer(src: tuple, dst: tuple, cap: float) -> dict:
    """src(top1, cov, y)로 적합한 규칙을 dst에서 평가합니다."""
    rule = fit_none_rule(*src, cap=cap)
    return {"rule": rule, **confusion(apply_rule(rule, dst[0], dst[1]), dst[2])}


def passes_target(t: dict) -> bool:
    return t["f1"] >= TRANSFER_TARGET["min_f1"] and t["false_none"] <= TRANSFER_TARGET["max_false_none"]


def main(argv=None) -> int:
    from theseus_engine.config import get_tool_rag_settings
    from theseus_engine.core.tool_rag.cache import EmbeddingCache
    from theseus_engine.core.tool_rag.retriever import ToolRetriever
    from theseus_engine.core.tool_rag.text import RECIPE_VERSION

    ap = argparse.ArgumentParser(prog="python -m benchmarks.tool_rag.calibrate")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--cap", type=float, default=0.05, help="false-none 상한(답 있는 질의 중 none 판정 비율)")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)

    settings = dataclasses.replace(
        get_tool_rag_settings(), embed_threads=args.threads, feedback="off", cache_dir=None, none_mode="off"
    )
    retr = ToolRetriever(settings=settings, cache=EmbeddingCache(None), none_rule=None)
    index = retr.get_index(harness.build_registry("core"))
    sources = {
        "dev": harness.load_eval_set("dev", "core"),  # test·holdout은 읽지 않습니다.
        "calibration_set": load_calibration_set("core"),
    }
    data = {}
    for key, rows in sources.items():
        feats = [retr.score(r["query"], index)[1:] for r in rows]
        data[key] = (
            np.array([f[0] for f in feats]),
            np.array([f[1] for f in feats]),
            np.array([int(r["type"] == "none") for r in rows]),
        )
    top1, cov, y = (np.concatenate([data[k][i] for k in sources]) for i in range(3))

    rule = fit_none_rule(top1, cov, y, cap=args.cap)
    cv = cv_none(top1, cov, y, cap=args.cap)
    c2d = transfer(data["calibration_set"], data["dev"], args.cap)
    d2c = transfer(data["dev"], data["calibration_set"], args.cap)
    in_sample = {k: confusion(apply_rule(rule, *data[k][:2]), data[k][2]) for k in sources}
    in_sample["pooled"] = confusion(apply_rule(rule, top1, cov), y)
    target_met = passes_target(c2d) and passes_target(d2c)
    out = {
        "embedder_fingerprint": retr.embedder().fingerprint,
        "recipe_version": RECIPE_VERSION,
        "none_rule": rule,
        "equivalent": f"top1 + {rule['w_cov'] / rule['w_top1']:.4f}*cov < {-rule['b'] / rule['w_top1']:.5f} -> none",
        "fit": {
            "data": {
                "dev": {"source": "eval_set.jsonl split=dev registry=core", "n": int(len(data["dev"][2])),
                        "n_none": int(data["dev"][2].sum()), "sha256": harness.EVAL_SET_SHA256},
                "calibration_set": {"source": "calibration_set.jsonl registry=core",
                                    "n": int(len(data["calibration_set"][2])),
                                    "n_none": int(data["calibration_set"][2].sum()), "sha256": CALIBRATION_SET_SHA256},
            },
            "registry": "core",
            "n": int(len(y)),
            "n_none": int(y.sum()),
            "method": "class-balanced L2 logistic regression [top1, cov] on pooled dev + calibration_set, "
            "threshold = max F1 with false-none <= cap",
            "cap": args.cap,
            "in_sample": in_sample,
            "cv_5fold_x20_pooled": cv,
            "transfer": {"calibration_set_to_dev": c2d, "dev_to_calibration_set": d2c},
            "decision": {
                "target": TRANSFER_TARGET,
                "target_met_both_directions": target_met,
                "runtime_default": "soft" if target_met else "off",
                "note": "THESEUS_TOOL_RAG_NONE_MODE 기본값은 off. 이 규칙은 soft로 켤 때만 쓰입니다."
                if not target_met
                else "양방향 전이 기준을 넘음",
            },
            "date": dt.date.today().isoformat(),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
