"""두 하네스 결과 JSON을 질의 단위 paired bootstrap으로 비교합니다(보고용, 튜닝에 쓰지 않음).

    python -m benchmarks.tool_rag.compare results/baseline_test.json results/v2_test.json

지표별로 (B − A) 평균 차이와 95% 신뢰구간(질의 재표본 10000회, seed 0), 질의별 증가/감소 수를 출력합니다.
  R@3                  유사도 슬롯 평가 대상(정답 type != none, 필수 외 정답 있음)
  set_recall_delivered 실제 전달 집합의 정답 재현율(필수 포함 정답)
  전달 스키마 토큰     전달 집합 to_api_schema 압축 JSON의 cl100k 토큰 합
  전달 도구 수
두 파일은 같은 분할·레지스트리여야 하고 per_item이 들어 있어야 합니다(--no-per-item으로 만든 파일은 안 됨).
"""

from __future__ import annotations

from . import _env  # noqa: F401  # 반드시 theseus_engine보다 먼저

import argparse
import json
from pathlib import Path

import numpy as np

from . import harness


def per_query(result: dict, tokens: dict[str, int]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {"r3": {}, "set_recall": {}, "tokens": {}, "n_tools": {}}
    for x in result["per_item"]:
        top = [n for n, _ in x["pred_sim_top8"]]
        if x["type"] != "none" and x["gold_ne"]:
            out["r3"][x["id"]] = len(set(top[:3]) & set(x["gold_ne"])) / len(x["gold_ne"])
        if x["type"] != "none" and x["gold_full"]:
            out["set_recall"][x["id"]] = len(set(x["gold_full"]) & set(x["delivered"])) / len(x["gold_full"])
        out["tokens"][x["id"]] = float(sum(tokens[n] for n in x["delivered"]))
        out["n_tools"][x["id"]] = float(len(x["delivered"]))
    return out


def paired_bootstrap(a: dict, b: dict, n: int = 10000, seed: int = 0) -> dict:
    keys = sorted(set(a) & set(b))
    d = np.array([b[k] - a[k] for k in keys])
    boots = d[np.random.default_rng(seed).integers(0, len(d), (n, len(d)))].mean(1)
    return {
        "a": float(np.mean([a[k] for k in keys])),
        "b": float(np.mean([b[k] for k in keys])),
        "delta": float(d.mean()),
        "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
        "wins": int((d > 0).sum()),
        "losses": int((d < 0).sum()),
        "n": len(keys),
    }


def main(argv=None) -> int:
    from theseus_engine.tools.core.tool_search_tool import ToolSearchTool

    ap = argparse.ArgumentParser(prog="python -m benchmarks.tool_rag.compare")
    ap.add_argument("a", type=Path, help="기준 결과(예: baseline)")
    ap.add_argument("b", type=Path, help="비교 결과(예: v2)")
    ap.add_argument("--json", dest="json_out", type=Path)
    args = ap.parse_args(argv)

    ra, rb = (json.loads(p.read_text(encoding="utf-8")) for p in (args.a, args.b))
    for key in ("split", "registry"):
        if ra["meta"][key] != rb["meta"][key]:
            raise SystemExit(f"{key}가 다릅니다: {ra['meta'][key]} vs {rb['meta'][key]}")
    reg = harness.build_registry(ra["meta"]["registry"])
    tokens = {t.name: harness.schema_tokens(t) for t in reg.list_tools()}
    tokens.setdefault("tool_search", harness.schema_tokens(ToolSearchTool()))
    va, vb = per_query(ra, tokens), per_query(rb, tokens)
    report = {
        "a": str(args.a.name),
        "b": str(args.b.name),
        "split": ra["meta"]["split"],
        "registry": ra["meta"]["registry"],
        "metrics": {k: paired_bootstrap(va[k], vb[k]) for k in va},
    }
    labels = {"r3": "R@3", "set_recall": "set_recall_delivered", "tokens": "전달 스키마 토큰", "n_tools": "전달 도구 수"}
    print(f"{args.a.name} → {args.b.name}  (split={report['split']}, registry={report['registry']})")
    for key, m in report["metrics"].items():
        print(
            f"  {labels[key]:22s} {m['a']:.3f} → {m['b']:.3f}  Δ {m['delta']:+.3f} "
            f"[95% CI {m['ci95'][0]:+.3f}, {m['ci95'][1]:+.3f}]  증가 {m['wins']} / 감소 {m['losses']} (n={m['n']})"
        )
    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
