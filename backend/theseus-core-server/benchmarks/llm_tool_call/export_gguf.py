"""LoRA 어댑터를 bf16 원본에 합치고 GGUF로 바꾼 뒤 양자화합니다(CPU에서 동작, GPU 불필요).

  1. (어댑터가 있으면) peft로 bf16 원본에 LoRA를 합쳐 safetensors로 저장
  2. llama.cpp convert_hf_to_gguf.py로 bf16 GGUF 생성(chat template은 tokenizer_config.json의 것이 들어감)
  3. llama-quantize로 Q4_K_M 등 양자화(운영과 같은 방식으로 비교하려고 기본 Q4_K_M)

예)
  python -m benchmarks.llm_tool_call.export_gguf --base <bf16 디렉터리> --adapter <runs/x/adapter> \\
      --llama-cpp <llama.cpp b12655 디렉터리> --work <출력 디렉터리> --name run1-r16 --quant Q4_K_M
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True)
    p.add_argument("--adapter", default=None, help="없으면 원본을 그대로 변환(양자화 대조군)")
    p.add_argument("--llama-cpp", required=True, help="bin/과 src/llama.cpp-*/가 있는 디렉터리")
    p.add_argument("--work", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--quant", nargs="+", default=["Q4_K_M"])
    p.add_argument("--imatrix", default=None, help="llama-imatrix로 만든 .imatrix 파일(선택)")
    args = p.parse_args()

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    lc = Path(args.llama_cpp)
    src = next(lc.glob("src/llama.cpp-*"))
    t0 = time.time()

    hf_dir = Path(args.base)
    if args.adapter:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        merged = work / f"{args.name}-merged"
        if not (merged / "config.json").exists():
            model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.bfloat16, device_map="cpu")
            model = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
            model.save_pretrained(str(merged), safe_serialization=True, max_shard_size="4GB")
            AutoTokenizer.from_pretrained(args.base).save_pretrained(str(merged))  # 원본 토크나이저·chat template 유지
            for extra in ("generation_config.json",):
                if (Path(args.base) / extra).exists():
                    shutil.copy(Path(args.base) / extra, merged / extra)
            print(f"merged -> {merged} ({time.time() - t0:.0f}s)", flush=True)
        hf_dir = merged

    bf16 = work / f"{args.name}-bf16.gguf"
    if not bf16.exists():
        subprocess.run([sys.executable, str(src / "convert_hf_to_gguf.py"), str(hf_dir), "--outtype", "bf16", "--outfile", str(bf16)], check=True)
        print(f"gguf bf16 -> {bf16} ({time.time() - t0:.0f}s)", flush=True)

    quantize = lc / "bin" / ("llama-quantize.exe" if sys.platform == "win32" else "llama-quantize")
    for q in args.quant:
        out = work / f"{args.name}-{q}{'-imat' if args.imatrix else ''}.gguf"
        if out.exists():
            continue
        cmd = [str(quantize)]
        if args.imatrix:
            cmd += ["--imatrix", args.imatrix]
        cmd += [str(bf16), str(out), q]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        print(f"{q} -> {out} ({out.stat().st_size / 2**30:.2f} GiB, {time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
