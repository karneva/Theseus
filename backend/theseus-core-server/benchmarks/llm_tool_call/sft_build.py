"""datagen validate가 쓴 sft.jsonl을 학습용 (prompt, target) 문자열로 렌더링합니다.

렌더링은 운영과 같아야 합니다. 운영 Ollama는 도구 스키마를 Go 구조체로 축약하고 도구 호출 인자를 객체로 바꾼 뒤
GGUF chat template으로 렌더링합니다(ollama_render.py). 프롬프트 부분은 HF 토크나이저의 chat template과 llama.cpp
렌더링이 문자 단위로 같음을 확인했습니다. 그래서 축약한 요청을 HF chat template으로 렌더링하고, 정답 assistant 턴은
"전체 렌더링 - 프롬프트 렌더링"으로 얻습니다(모델이 <|im_start|>assistant 뒤에 생성해야 하는 문자열).

예)
  python -m benchmarks.llm_tool_call.sft_build --inp data/run1/sft.jsonl --exclude data/run1/exclude_edits.json \\
      --tokenizer <Qwen3-4B-Instruct-2507 디렉터리> --out data/run1/train.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from benchmarks.llm_tool_call.ollama_render import reduce_messages, reduce_tool


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--inp", required=True, nargs="+", help="validate가 쓴 sft.jsonl(여러 개면 합침, 예: run1 재검증분 + run2 신규)")
    p.add_argument("--exclude", default=None, help="뺄 에피소드 id JSON 목록(사람·에이전트 검수에서 틀린 것)")
    p.add_argument("--cap-episodes", default=None, help='범주별 최대 에피소드 수 JSON(예: {"memory": 30}). 넘으면 seed로 무작위 추림')
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--max-tokens", type=int, default=10240)
    p.add_argument("--val-frac", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer)
    exclude = set(json.loads(Path(args.exclude).read_text(encoding="utf-8"))) if args.exclude else set()
    rows = [json.loads(line) for inp in args.inp for line in Path(inp).open(encoding="utf-8") if line.strip()]
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate example ids across inputs"
    rng = random.Random(args.seed)
    capped: list[str] = []
    for cat, cap in (json.loads(args.cap_episodes) if args.cap_episodes else {}).items():
        eps = sorted({r["episode"] for r in rows if r["category"] == cat and r["episode"] not in exclude})
        if len(eps) > cap:
            capped += sorted(set(eps) - set(rng.sample(eps, cap)))
    exclude |= set(capped)
    episodes = sorted({r["episode"] for r in rows if r["episode"] not in exclude})
    val_eps = set(rng.sample(episodes, max(1, round(len(episodes) * args.val_frac))))
    out, dropped = [], {"excluded": 0, "too_long": 0}
    for r in rows:
        if r["episode"] in exclude:
            dropped["excluded"] += 1
            continue
        msgs = reduce_messages(r["messages"])
        tools = [reduce_tool(t) for t in r["tools"]]
        prompt = tok.apply_chat_template(msgs[:-1], tools=tools, add_generation_prompt=True, tokenize=False)
        full = tok.apply_chat_template(msgs, tools=tools, tokenize=False)
        assert full.startswith(prompt), r["id"]
        target = full[len(prompt) :].rstrip("\n")
        assert target.endswith("<|im_end|>"), (r["id"], target[-40:])
        n_prompt = len(tok(prompt, add_special_tokens=False)["input_ids"])
        n_target = len(tok(target, add_special_tokens=False)["input_ids"])
        if n_prompt + n_target > args.max_tokens:
            dropped["too_long"] += 1
            continue
        out.append(
            {
                "id": r["id"],
                "episode": r["episode"],
                "category": r["category"],
                "lang": r["lang"],
                "turn": r["turn"],
                "split": "val" if r["episode"] in val_eps else "train",
                "prompt": prompt,
                "target": target,
                "n_prompt": n_prompt,
                "n_target": n_target,
            }
        )
    with Path(args.out).open("w", encoding="utf-8", newline="\n") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    lens = sorted(r["n_prompt"] + r["n_target"] for r in out)
    print(
        json.dumps(
            {
                "examples": len(out),
                "train": sum(r["split"] == "train" for r in out),
                "val": sum(r["split"] == "val" for r in out),
                "dropped": {**dropped, "capped_episodes": len(capped)},
                "episodes_by_category": {c: len({r["episode"] for r in out if r["category"] == c}) for c in sorted({r["category"] for r in out})},
                "tokens_p50_p90_max": [lens[len(lens) // 2], lens[int(0.9 * (len(lens) - 1))], lens[-1]] if lens else None,
                "target_tokens_mean": round(statistics.fmean(r["n_target"] for r in out), 1) if out else None,
                "train_target_tokens_total": sum(r["n_target"] for r in out if r["split"] == "train"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
