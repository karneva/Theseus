"""Tool RAG 임베딩 모델 디렉터리를 만듭니다(ONNX 동적 int8 + sentencepiece).

Docker 빌드의 builder 단계에서 실행해 결과 디렉터리만 런타임 이미지에 복사합니다. 양자화 peak 메모리가 약 2.4 GB라서
3.8 GB 서버의 런타임에서 돌리면 안 됩니다. 로컬 개발(CLI)에서는 노트북에서 한 번 돌리면 됩니다.

    # 허깅페이스에서 고정 리비전을 받아 int8로 변환 (builder 전용 의존성: onnx, onnxruntime, huggingface-hub)
    python scripts/provision_tool_rag_model.py --out ~/.theseus/models/e5-small-int8

    # 이미 받아 둔 스냅샷 디렉터리(onnx/model.onnx, sentencepiece.bpe.model)에서 오프라인으로
    python scripts/provision_tool_rag_model.py --source-dir <HF snapshot> --out <dir>

    # 양자화 없이 fp32 ONNX(torch와 순위 동일, RSS 약 +517 MB)
    python scripts/provision_tool_rag_model.py --quantization fp32 --out <dir>

만드는 파일: model.onnx, sentencepiece.bpe.model, embedder.json.
none 판정 보정값은 theseus_engine/core/tool_rag/data/에 동봉돼 있고, 모델 sha256이 같을 때만 적용됩니다.
그래서 sha256이 기대값과 다르면 기본적으로 실패합니다(--allow-hash-mismatch로 무시 가능, 그때는 none 판정이 꺼집니다).

양자화 설정은 optimum AutoQuantizationConfig.avx2(is_static=False)와 같습니다: 가중치 uint8 대칭 per-channel,
활성값 uint8 비대칭(동적), 상수가 아닌 B 입력 MatMul(어텐션)까지 양자화. 같은 onnx/onnxruntime 버전이면
sentence-transformers export_dynamic_quantized_onnx_model(avx2) 출력과 바이트 단위로 같습니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
FP32_FILE = "onnx/model.onnx"
SPM_FILE = "sentencepiece.bpe.model"
EXPECTED_SHA256 = {
    "fp32": "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665",
    "int8": "7486bedf9a52c6bab73586272c5bdc866ac077a77d6aac4ff1d8f3bdb02c7610",
    "spm": "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_sources(source_dir: Path | None) -> tuple[Path, Path]:
    if source_dir is not None:
        return source_dir / FP32_FILE, source_dir / SPM_FILE
    from huggingface_hub import hf_hub_download

    fp32 = hf_hub_download(REPO_ID, FP32_FILE, revision=REVISION)
    spm = hf_hub_download(REPO_ID, SPM_FILE, revision=REVISION)
    return Path(fp32), Path(spm)


def quantize_int8(src: Path, dst: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(
        str(src),
        str(dst),
        weight_type=QuantType.QUInt8,
        per_channel=True,
        reduce_range=False,
        extra_options={"WeightSymmetric": True, "ActivationSymmetric": False, "MatMulConstBOnly": False},
    )


def check(label: str, actual: str, expected: str, allow_mismatch: bool) -> bool:
    ok = actual == expected
    print(f"  {label}: {actual} {'OK' if ok else '!= expected ' + expected}")
    if not ok and not allow_mismatch:
        raise SystemExit(f"{label} sha256이 기대값과 다릅니다. onnx/onnxruntime 버전을 확인하세요.")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="모델 디렉터리(THESEUS_EMBED_MODEL_DIR)")
    ap.add_argument("--source-dir", type=Path, help="HF 스냅샷 디렉터리(있으면 내려받지 않음)")
    ap.add_argument("--quantization", choices=("int8", "fp32"), default="int8")
    ap.add_argument("--allow-hash-mismatch", action="store_true")
    args = ap.parse_args(argv)

    out: Path = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    fp32_path, spm_path = fetch_sources(args.source_dir)
    print(f"source: {REPO_ID}@{REVISION}")
    check("fp32 source", sha256(fp32_path), EXPECTED_SHA256["fp32"], args.allow_hash_mismatch)
    check("sentencepiece", sha256(spm_path), EXPECTED_SHA256["spm"], args.allow_hash_mismatch)

    target = out / "model.onnx"
    if args.quantization == "int8":
        with tempfile.TemporaryDirectory(dir=out) as tmp:
            tmp_model = Path(tmp) / "model.onnx"
            quantize_int8(fp32_path, tmp_model)
            shutil.move(str(tmp_model), target)
        quantization = "onnxruntime dynamic int8 (QUInt8 per-channel symmetric weights, MatMulConstBOnly=False; = optimum avx2)"
    else:
        shutil.copyfile(fp32_path, target)
        quantization = "none (fp32)"
    model_sha = sha256(target)
    check(f"{args.quantization} model", model_sha, EXPECTED_SHA256[args.quantization], args.allow_hash_mismatch)
    shutil.copyfile(spm_path, out / SPM_FILE)

    try:
        import onnxruntime

        ort_version = onnxruntime.__version__
    except Exception:
        ort_version = None
    meta = {
        "base_model": REPO_ID,
        "revision": REVISION,
        "source_file": FP32_FILE,
        "source_sha256": EXPECTED_SHA256["fp32"],
        "sha256": model_sha,
        "tokenizer": SPM_FILE,
        "tokenizer_sha256": EXPECTED_SHA256["spm"],
        "dim": 384,
        "max_length": 512,
        "pooling": "mean",
        "normalize": True,
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "quantization": quantization,
        "onnxruntime_version": ort_version,
        "license": "MIT (intfloat/multilingual-e5-small)",
    }
    (out / "embedder.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    size_mb = target.stat().st_size / 2**20
    print(f"wrote {out} (model {size_mb:.1f} MiB, {time.perf_counter() - started:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
