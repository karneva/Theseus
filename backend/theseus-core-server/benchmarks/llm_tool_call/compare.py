"""두 결과 JSON의 질의별 paired bootstrap 비교(원래 라벨과 label_adjust.json 보정 라벨 모두).

질의마다 샘플 평균을 내고, 두 모델에 공통인 질의를 복원 추출해 평균 차이의 95% 신뢰구간과 양측 p값을 냅니다.
지표마다 분모가 다릅니다: success_at_1·success_at_k·wrong_action은 정답이 있는 질의, none_at_1은 none 질의,
harmful_action·ask_user는 전체 질의입니다(run.summarize와 같은 정의).

사용: (backend/theseus-core-server에서)
    python -m benchmarks.llm_tool_call.compare --a results/base.json --b results/run2.json [--out cmp.json]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from benchmarks.llm_tool_call import harness

METRICS = {
    # 이름: (질의 필터, 실행별 값)
    "success_at_1": (lambda r: r["type"] != "none", lambda r: r["success_at_1"]),
    "success_at_k": (lambda r: r["type"] != "none", lambda r: r["success_at_k"]),
    # 웹 서버에서는 ask_user가 사용자에게 닿지 않으므로(#59) ask_user를 부른 실행을 실패로 친 첫 턴 정답률
    "success_at_1_no_ask": (lambda r: r["type"] != "none", lambda r: r["success_at_1"] and not harness.called_ask_user(r)),
    "none_at_1": (lambda r: r["type"] == "none", lambda r: r["success_at_1"]),
    "wrong_action_rate": (lambda r: r["type"] != "none", lambda r: r["stop"] == "other_action"),
    "harmful_action_rate": (lambda r: True, harness.harmful_action),
    "ask_user_rate": (lambda r: True, harness.called_ask_user),
    "error_rate": (lambda r: True, lambda r: r["error"] is not None),
}


def case_means(items: list[dict], adjust: dict | None) -> dict[str, dict[str, float]]:
    """{지표: {질의 id: 샘플 평균}}. adjust가 있으면 보정 라벨로 다시 채점하고 제외 질의를 뺍니다."""
    if adjust is not None:
        items = [a for a in (harness.adjust_item(r, adjust) for r in items) if a is not None]
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in items:
        by_case[r["id"]].append(r)
    out: dict[str, dict[str, float]] = {}
    for name, (keep, val) in METRICS.items():
        out[name] = {cid: statistics.fmean(1.0 if val(r) else 0.0 for r in rs) for cid, rs in by_case.items() if keep(rs[0])}
    return out


def paired(a: dict[str, float], b: dict[str, float], n_boot: int, seed: int) -> dict:
    ids = sorted(set(a) & set(b))
    if not ids:
        return {"n": 0}
    diffs = [b[i] - a[i] for i in ids]
    rng = random.Random(seed)
    n = len(ids)
    boots = sorted(statistics.fmean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(n_boot))
    delta = statistics.fmean(diffs)
    lo, hi = boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
    # 양측 p: 부트스트랩 분포에서 0 반대편 비율의 두 배(0이 분포 밖이면 1/n_boot 미만으로 표기)
    if delta > 0:
        p = 2 * sum(x <= 0 for x in boots) / n_boot
    elif delta < 0:
        p = 2 * sum(x >= 0 for x in boots) / n_boot
    else:
        p = 1.0
    return {
        "n": n,
        "a": round(statistics.fmean(a[i] for i in ids), 4),
        "b": round(statistics.fmean(b[i] for i in ids), 4),
        "delta": round(delta, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "p": round(min(1.0, p), 4),
        "b_higher": sum(d > 0 for d in diffs),
        "b_lower": sum(d < 0 for d in diffs),
        "changed": [{"id": i, "a": round(a[i], 2), "b": round(b[i], 2)} for i in ids if a[i] != b[i]],
    }


def compare(a_path: Path, b_path: Path, n_boot: int = 10000, seed: int = 0) -> dict:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (a_path, b_path))
    adj = harness.load_label_adjust()
    out: dict = {
        "a": {"path": str(a_path), "model": a["meta"].get("model"), "samples": a["summary"]["samples"]},
        "b": {"path": str(b_path), "model": b["meta"].get("model"), "samples": b["summary"]["samples"]},
        "n_boot": n_boot,
        "seed": seed,
    }
    for label, ad in (("raw", None), ("adjusted", adj or None)):
        if label == "adjusted" and ad is None:
            continue
        ca, cb = case_means(a["per_item"], ad), case_means(b["per_item"], ad)
        out[label] = {m: paired(ca[m], cb[m], n_boot, seed) for m in METRICS}
    out["latency"] = {
        k: {"a": a["summary"].get(k), "b": b["summary"].get(k)}
        for k in ("latency_first_p50_s", "latency_first_p95_s", "latency_total_p50_s")
    }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--a", required=True, type=Path, help="기준 결과 JSON")
    p.add_argument("--b", required=True, type=Path, help="비교 결과 JSON(delta = b - a)")
    p.add_argument("--n-boot", type=int, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    res = compare(args.a, args.b, args.n_boot, args.seed)
    if args.out:
        args.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for label in ("raw", "adjusted"):
        if label not in res:
            continue
        print(f"[{label}] {res['a']['model']} -> {res['b']['model']}")
        for m, s in res[label].items():
            if s.get("n"):
                print(f"  {m:20s} n={s['n']:3d} {s['a']:.3f} -> {s['b']:.3f}  Δ{s['delta']:+.3f} CI[{s['ci95'][0]:+.3f},{s['ci95'][1]:+.3f}] p={s['p']:.3f}  +{s['b_higher']}/-{s['b_lower']}")
    print("latency", json.dumps(res["latency"]))


if __name__ == "__main__":
    main()
