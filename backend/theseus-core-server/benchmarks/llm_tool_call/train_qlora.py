"""Qwen3-4B-Instruct-2507 QLoRA 학습(Unsloth 4bit + LoRA, 6GB GPU용).

sft_build.py가 만든 (prompt, target)으로 정답 assistant 턴 토큰에만 손실을 줍니다. 프롬프트가 길고(중앙값 약 5k,
최대 10k 토큰) 정답은 짧으므로(평균 약 44 토큰), 어휘 전체 로짓은 정답 위치만 계산합니다(logits_to_keep).
배치는 1개씩 넣고 기울기 누적으로 묶으며, 손실은 누적 구간의 정답 토큰 수로 평균냅니다.

예)
  python -m benchmarks.llm_tool_call.train_qlora --data data/run1/train.jsonl --model <bf16 디렉터리> --out <어댑터 디렉터리>
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--warmup", type=int, default=5, help="최적화 스텝 기준")
    p.add_argument("--max-seq", type=int, default=10240)
    p.add_argument("--max-steps", type=int, default=None, help="최적화 스텝 상한(점검용)")
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()

    import torch
    from unsloth import FastLanguageModel  # noqa: I001  (unsloth는 transformers보다 먼저)
    import bitsandbytes as bnb

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    rows = [json.loads(line) for line in Path(args.data).open(encoding="utf-8") if line.strip()]
    train = [r for r in rows if r["split"] == "train"]
    val = [r for r in rows if r["split"] == "val"]

    model, tok = FastLanguageModel.from_pretrained(model_name=args.model, max_seq_length=args.max_seq, load_in_4bit=True, dtype=None)
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    def encode(r):
        pi = tok(r["prompt"], add_special_tokens=False)["input_ids"]
        ti = tok(r["target"], add_special_tokens=False)["input_ids"]
        return torch.tensor([pi + ti], device="cuda"), len(ti)

    def target_loss(ids, k):
        # 위치 t의 로짓이 t+1 토큰을 예측: 마지막 k+1개 위치의 로짓 중 앞 k개가 정답 k 토큰을 예측합니다.
        out = model(input_ids=ids, logits_to_keep=k + 1)
        logits = out.logits[0, :-1, :].float()
        labels = ids[0, -k:]
        return torch.nn.functional.cross_entropy(logits, labels, reduction="sum"), k

    params = [p_ for p_ in model.parameters() if p_.requires_grad]
    opt = bnb.optim.AdamW8bit(params, lr=args.lr, weight_decay=0.0)
    total_steps = math.ceil(len(train) * args.epochs / args.grad_accum)
    if args.max_steps:
        total_steps = min(total_steps, args.max_steps)

    def lr_at(step):
        if step < args.warmup:
            return args.lr * (step + 1) / args.warmup
        prog = (step - args.warmup) / max(1, total_steps - args.warmup)
        return args.lr * 0.5 * (1 + math.cos(math.pi * min(1.0, prog)))

    def evaluate():
        model.eval()
        tot, n = 0.0, 0
        with torch.no_grad():
            for r in val:
                ids, k = encode(r)
                loss, kk = target_loss(ids, k)
                tot += float(loss)
                n += kk
        model.train()
        return tot / max(1, n)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (out_dir / "train_log.jsonl").open("a", encoding="utf-8")

    def emit(obj):
        line = json.dumps(obj, ensure_ascii=False)
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    emit({"event": "start", "train": len(train), "val": len(val), "total_steps": total_steps, **{k: v for k, v in vars(args).items()}})
    emit({"event": "eval", "step": 0, "val_loss": round(evaluate(), 4)})
    model.train()
    step, micro, acc_loss, acc_tok, started = 0, 0, 0.0, 0, time.time()
    order: list[dict] = []
    epoch = 0
    while step < total_steps:
        if not order:
            order = train[:]
            random.shuffle(order)
            epoch += 1
        r = order.pop()
        ids, k = encode(r)
        loss, kk = target_loss(ids, k)
        # 누적 구간 평균을 위해 대략적인 구간 토큰 수(평균 정답 길이 × 누적)로 나눕니다.
        (loss / (44.0 * args.grad_accum)).backward()
        acc_loss += float(loss)
        acc_tok += kk
        micro += 1
        if micro % args.grad_accum == 0:
            for g in opt.param_groups:
                g["lr"] = lr_at(step)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            emit(
                {
                    "event": "step",
                    "step": step,
                    "epoch": epoch,
                    "loss": round(acc_loss / max(1, acc_tok), 4),
                    "lr": round(lr_at(step - 1), 7),
                    "elapsed_s": round(time.time() - started, 1),
                    "max_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
                }
            )
            acc_loss, acc_tok = 0.0, 0
            if step % 30 == 0 or step == total_steps:
                emit({"event": "eval", "step": step, "val_loss": round(evaluate(), 4)})
    model.save_pretrained(str(out_dir / "adapter"))
    tok.save_pretrained(str(out_dir / "adapter"))
    emit({"event": "done", "steps": step, "elapsed_s": round(time.time() - started, 1)})


if __name__ == "__main__":
    main()
