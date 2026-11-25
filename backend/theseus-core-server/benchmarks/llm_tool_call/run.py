"""LLM 도구 호출 평가 CLI.

예)
  python -m benchmarks.llm_tool_call.run --split dev --model qwen3:4b-instruct-2507-q4_K_M \\
      --base-url http://127.0.0.1:11435/v1 --samples 3 --out benchmarks/llm_tool_call/results/base_q4km_dev.json

평가 프로토콜은 README.md를 보세요(dev로만 개발, test·holdout은 최종 구성에 한 번).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from benchmarks.tool_rag import _env  # noqa: F401  # 반드시 가장 먼저

SPLITS = ("dev", "test", "holdout", "final", "all")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--split", choices=SPLITS, default="dev", help="final = test + holdout")
    p.add_argument("--model", required=False, help="Ollama 모델 이름(THESEUS_MODEL의 ollama/ 뒤)")
    p.add_argument("--base-url", default="http://127.0.0.1:11435/v1", help="OpenAI 호환 엔드포인트(OLLAMA_BASE_URL)")
    p.add_argument("--samples", type=int, default=5, help="질의당 반복 횟수(seed = seed_base + i). 3회는 질의별 해상도가 0.33이라 run1부터 5회")
    p.add_argument("--seed-base", type=int, default=1)
    p.add_argument("--temperature", type=float, default=None, help="주면 요청에 넣음. 기본은 운영처럼 보내지 않음")
    p.add_argument("--limit", type=int, default=None, help="앞에서 n개만(빠른 점검용)")
    p.add_argument("--timeout", type=float, default=300.0, help="질의 1회(에피소드) 타임아웃(초)")
    p.add_argument("--max-turns", type=int, default=3, help="success@k의 k: 탐색 도구만 부르는 동안 이어갈 최대 LLM 턴 수")
    p.add_argument("--embed-model-dir", default=os.environ.get("THESEUS_EMBED_MODEL_DIR") or str(Path.home() / ".theseus/models/e5-small-int8"))
    p.add_argument("--fixture-dir", default=None, help="이 디렉터리를 fixture로 그대로 씀(컨테이너에서 /app). 없으면 git 스냅샷을 임시로 만듦")
    p.add_argument("--tag", default="", help="결과 meta에 남길 설명(예: base-q4km)")
    p.add_argument("--out", required=True)
    p.add_argument("--rescore", default=None, help="LLM을 부르지 않고 이 결과 JSON의 per_item을 현재 채점 규칙으로 다시 집계해 --out에 씀")
    return p.parse_args()


def rescore(src: Path, out: Path) -> None:
    """저장된 결과를 현재 채점 규칙(되묻는 본문 인정)으로 다시 집계합니다. per_item 원본 호출·본문은 그대로입니다."""
    from benchmarks.llm_tool_call import harness

    old = json.loads(src.read_text(encoding="utf-8"))
    items = [harness.apply_clarify_rule(dict(r)) for r in old["per_item"]]
    per_sample: dict[int, list[dict]] = defaultdict(list)
    for r in items:
        per_sample[r["sample"]].append(r)
    result = build_result([per_sample[k] for k in sorted(per_sample)])
    result["meta"] = {**old["meta"], "rescored_from": old["meta"].get("rescored_from") or src.name, "scoring": "clarify_text_accepted"}
    result["per_item"] = items
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1))


def _configure_env(args: argparse.Namespace) -> None:
    # src.config(Settings)와 theseus_engine.config가 import 시점에 읽으므로 import 전에 설정합니다.
    os.environ["THESEUS_MODEL"] = f"ollama/{args.model}"
    os.environ["OLLAMA_BASE_URL"] = args.base_url
    os.environ["THESEUS_EMBED_MODEL_DIR"] = args.embed_model_dir
    os.environ.setdefault("THESEUS_LLM_MAX_RETRIES", "2")
    os.environ.setdefault("THESEUS_DEBUG_DUMP", "false")


def _load_cases(split: str) -> list[dict]:
    from benchmarks.tool_rag.harness import load_eval_set

    if split == "final":
        return load_eval_set("test", registry="server") + load_eval_set("holdout", registry="server")
    if split == "all":
        return load_eval_set("all", registry="server") + load_eval_set("holdout", registry="server")
    return load_eval_set(split, registry="server")


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, cwd=_env.SERVER_DIR, timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def _pctl(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))
    return round(xs[k], 3)


def summarize(items: list[dict]) -> dict:
    """한 샘플(질의당 1회) 결과의 지표."""
    from benchmarks.llm_tool_call import harness

    answerable = [r for r in items if r["type"] != "none"]
    nones = [r for r in items if r["type"] == "none"]
    retrievable = [r for r in answerable if r["retrievable"]]
    multi = [r for r in answerable if r["type"] == "multi"]
    calls_total = sum(r["calls_total"] for r in items)
    calls_valid = sum(r["calls_args_valid"] for r in items)
    return {
        "n": len(items),
        "success_at_1": _mean([r["success_at_1"] for r in answerable]),
        "success_at_k": _mean([r["success_at_k"] for r in answerable]),
        "success_at_k_valid": _mean([r["success_at_k_valid"] for r in answerable]),
        "success_at_k_retrievable": _mean([r["success_at_k"] for r in retrievable]),
        "retrievable_rate": _mean([r["retrievable"] for r in answerable]),
        "none_at_1": _mean([r["success_at_1"] for r in nones]),
        "none_at_k": _mean([r["success_at_k"] for r in nones]),
        "turns_to_success_mean": _mean([r["turns_used"] for r in answerable if r["success_at_k"]]),
        "wrong_action_rate": _mean([r["stop"] == "other_action" for r in answerable]),
        "text_answer_rate": _mean([r["stop"] == "text_answer" for r in answerable]),
        "max_turns_rate": _mean([r["stop"] == "max_turns" for r in answerable]),
        "call_args_valid": round(calls_valid / calls_total, 4) if calls_total else None,
        "not_offered_call_rate": _mean([r["not_offered_call"] for r in items]),
        "text_tool_call_leak_rate": _mean([r["text_tool_call_leak"] for r in items]),
        "multi_relevant_called_frac": _mean([r["relevant_called_frac"] for r in multi]),
        "harmful_action_rate": _mean([harness.harmful_action(r) for r in items]),
        "ask_user_rate": _mean([harness.called_ask_user(r) for r in items]),
        "error_rate": _mean([r["error"] is not None for r in items]),
        "latency_first_p50_s": _pctl([r["latency_first_s"] for r in items], 0.5),
        "latency_first_p95_s": _pctl([r["latency_first_s"] for r in items], 0.95),
        "latency_total_p50_s": _pctl([r["latency_total_s"] for r in items], 0.5),
    }


def aggregate(per_sample: list[list[dict]]) -> dict:
    """샘플별 지표의 평균·표준편차, 그리고 질의별 평균 정답률로 낸 세부 분할."""
    sample_summaries = [summarize(items) for items in per_sample]
    keys = [k for k in sample_summaries[0] if k != "n"]
    summary = {"n": sample_summaries[0]["n"], "samples": len(per_sample)}
    for k in keys:
        vals = [s[k] for s in sample_summaries if s[k] is not None]
        summary[k] = round(statistics.fmean(vals), 4) if vals else None
        if k in ("success_at_1", "success_at_k", "none_at_1", "none_at_k", "call_args_valid", "harmful_action_rate") and len(vals) > 1:
            summary[f"{k}_sd"] = round(statistics.stdev(vals), 4)

    by_case: dict[str, list[dict]] = defaultdict(list)
    for items in per_sample:
        for r in items:
            by_case[r["id"]].append(r)
    case_acc = {cid: statistics.fmean(1.0 if r["success_at_k"] else 0.0 for r in rs) for cid, rs in by_case.items()}
    case_acc1 = {cid: statistics.fmean(1.0 if r["success_at_1"] else 0.0 for r in rs) for cid, rs in by_case.items()}
    breakdown: dict[str, dict] = {}
    first = per_sample[0]
    for dim in ("lang", "type", "split", "registry"):
        groups: dict[str, list[str]] = defaultdict(list)
        for r in first:
            groups[str(r[dim])].append(r["id"])
        breakdown[dim] = {
            g: {
                "n": len(ids),
                "success_at_1": round(statistics.fmean(case_acc1[i] for i in ids), 4),
                "success_at_k": round(statistics.fmean(case_acc[i] for i in ids), 4),
            }
            for g, ids in sorted(groups.items())
        }
    unstable = sorted(cid for cid, a in case_acc.items() if 0 < a < 1)
    return {
        "summary": summary,
        "per_sample": sample_summaries,
        "breakdown": breakdown,
        "case_success_at_k": case_acc,
        "case_success_at_1": case_acc1,
        "unstable_cases": unstable,
    }


def build_result(per_sample: list[list[dict]]) -> dict:
    """원래 라벨 기준 집계 + label_adjust.json을 적용한 보정 집계(adjusted)."""
    import hashlib

    from benchmarks.llm_tool_call import harness

    result = aggregate(per_sample)
    adj = harness.load_label_adjust()
    if adj:
        adjusted = [[a for a in (harness.adjust_item(r, adj) for r in items) if a is not None] for items in per_sample]
        agg = aggregate(adjusted)
        raw = harness.LABEL_ADJUST_PATH.read_bytes().replace(b"\r\n", b"\n")
        kept = {r["id"] for r in adjusted[0]}
        result["adjusted"] = {
            "label_adjust_sha256": hashlib.sha256(raw).hexdigest()[:16],
            "excluded": sorted({r["id"] for r in per_sample[0]} - kept),
            "accepted_also": sorted(cid for cid, rule in (adj.get("cases") or {}).items() if not rule.get("exclude") and cid in kept),
            "summary": agg["summary"],
            "breakdown": agg["breakdown"],
            "case_success_at_1": agg["case_success_at_1"],
            "case_success_at_k": agg["case_success_at_k"],
        }
    return result


async def _main(args: argparse.Namespace) -> dict:
    from benchmarks.llm_tool_call import harness

    harness.pin_environment_section()
    warm_s = harness.warmup_tool_rag()
    cases = _load_cases(args.split)
    if args.limit:
        cases = cases[: args.limit]
    owned = args.fixture_dir is None
    fixture = harness.make_fixture(_env.SERVER_DIR) if owned else Path(args.fixture_dir).resolve()
    stubs = harness.add_referenced_stubs(fixture, cases)
    harness.enter_fixture(fixture, _env.SERVER_DIR)
    try:
        return await _evaluate(args, cases, stubs, warm_s)
    finally:
        os.chdir(_env.SERVER_DIR)
        if owned:
            shutil.rmtree(fixture.parent, ignore_errors=True)


async def _evaluate(args: argparse.Namespace, cases: list[dict], stubs: list[str], warm_s: float) -> dict:
    from benchmarks.llm_tool_call import harness

    logging.getLogger().setLevel(logging.WARNING)

    per_sample: list[list[dict]] = []
    t0 = time.perf_counter()
    for i in range(args.samples):
        extra = {"seed": args.seed_base + i}
        if args.temperature is not None:
            extra["temperature"] = args.temperature
        items = []
        for j, case in enumerate(cases, 1):
            r = await harness.run_case(case, extra_body=extra, timeout_s=args.timeout, max_turns=args.max_turns)
            r["sample"] = i
            items.append(r)
            mark = "ERR" if r["error"] else ("ok1" if r["success_at_1"] else ("okk" if r["success_at_k"] else "x  "))
            path = ">".join("+".join(c["name"] for c in t["calls"]) or "TEXT" for t in r["turns"])
            print(f"[s{i} {j:3d}/{len(cases)}] {mark} {case['id']:>6} {path} ({r['stop']})", file=sys.stderr, flush=True)
        per_sample.append(items)
        print(json.dumps({"sample": i, **summarize(items)}, ensure_ascii=False), file=sys.stderr, flush=True)

    result = build_result(per_sample)
    import importlib.metadata as md

    result["meta"] = {
        "command": " ".join([Path(sys.executable).name, "-m", "benchmarks.llm_tool_call.run", *sys.argv[1:]]),
        "commit": _git_commit() or os.environ.get("BENCH_COMMIT"),
        "runtime": os.environ.get("BENCH_RUNTIME", "host"),
        "fixture": "given:" + args.fixture_dir if args.fixture_dir else "git-snapshot",
        "tag": args.tag,
        "model": args.model,
        "base_url_kind": "llm-gateway filter" if args.base_url.rstrip("/").endswith(":11435/v1") else "custom",
        "split": args.split,
        "samples": args.samples,
        "seed_base": args.seed_base,
        "temperature": args.temperature,
        "max_turns": args.max_turns,
        "scoring": "clarify_text_accepted",
        "fixture_stub_files": stubs,
        "tool_rag_warmup_s": round(warm_s, 2),
        "wall_s": round(time.perf_counter() - t0, 1),
        "python": platform.python_version(),
        "versions": {p: md.version(p) for p in ("openai", "pydantic", "fastapi", "onnxruntime")},
        "environment_section": harness.PINNED_ENVIRONMENT_SECTION,
    }
    result["per_item"] = [r for items in per_sample for r in items]
    return result


def main() -> None:
    args = _parse()
    args.out = str(Path(args.out).resolve())  # 실행 중 fixture로 chdir하므로 먼저 절대 경로로
    if args.rescore:
        rescore(Path(args.rescore), Path(args.out))
        return
    if not args.model:
        raise SystemExit("--model이 필요합니다")
    _configure_env(args)
    result = asyncio.run(_main(args))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
