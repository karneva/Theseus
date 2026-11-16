"""Tool RAG 평가 CLI.

    python -m benchmarks.tool_rag.run --variant baseline --split dev [--json out.json]

--variant
    baseline                      v1 ToolRetriever 동결 사본 (benchmarks/tool_rag/baseline.py, legacy_v1.py)
    v2                            저장소의 Tool RAG v2 구현 (benchmarks/tool_rag/v2.py)
    all-visible                   v1 서버 동작 참조점(검색 없이 보이는 도구 전부)
    package.module:ClassName      import 가능한 모듈의 클래스
    C:/path/to/my_variant.py:Cls  저장소 밖 파일의 클래스 (스크래치 실험용)
--variant-kwargs '{"k": 5}'       클래스 생성자 인자(JSON)
"""

from __future__ import annotations

from . import _env  # noqa: F401  # 반드시 가장 먼저

import argparse
import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path

from . import harness


def load_variant(spec: str, kwargs: dict):
    if spec == "baseline":
        from .baseline import BaselineRetriever

        return BaselineRetriever(**kwargs)
    if spec == "v2":
        from .v2 import V2Retriever

        return V2Retriever(**kwargs)
    if spec == "all-visible":
        from .v2 import AllVisibleTools

        return AllVisibleTools(**kwargs)
    if ":" not in spec:
        raise SystemExit(f"--variant는 'baseline', 'v2', 'module:Class', 'file.py:Class' 중 하나여야 합니다: {spec!r}")
    target, cls_name = spec.rsplit(":", 1)
    if target.endswith(".py"):
        path = Path(target).resolve()
        mod_name = f"_toolrag_variant_{path.stem}"
        mspec = importlib.util.spec_from_file_location(mod_name, path)
        if mspec is None or mspec.loader is None:
            raise SystemExit(f"변형 파일을 불러올 수 없습니다: {path}")
        module = importlib.util.module_from_spec(mspec)
        sys.modules[mod_name] = module
        mspec.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    return getattr(module, cls_name)(**kwargs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m benchmarks.tool_rag.run", description="Tool RAG 평가 하네스")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--variant-kwargs", default="{}", help="생성자 인자 JSON")
    ap.add_argument("--split", choices=harness.SPLITS, default="dev")
    ap.add_argument("--registry", choices=harness.REGISTRY_KINDS, default="core")
    ap.add_argument("--json", dest="json_out", help="전체 결과를 쓸 JSON 경로")
    ap.add_argument("--passes", type=int, default=3, help="웜 지연 측정 반복 횟수 (0이면 생략)")
    ap.add_argument("--threads", type=int, default=4, help="torch CPU 스레드 수 (uses_torch 변형만)")
    ap.add_argument("--no-per-item", action="store_true", help="항목별 예측을 결과에서 뺌")
    ap.add_argument(
        "--legacy-demo-tools",
        action="store_true",
        help="동결 베이스라인(2026-11-15) 재현용: 데모 도구 2개를 레지스트리에 다시 넣음",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    for name in ("theseus_engine", "sentence_transformers", "transformers", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.ERROR)

    retriever = load_variant(args.variant, json.loads(args.variant_kwargs))
    result = harness.evaluate(
        retriever,
        split=args.split,
        registry=args.registry,
        latency_passes=args.passes,
        threads=args.threads,
        include_per_item=not args.no_per_item,
        legacy_demo_tools=args.legacy_demo_tools,
    )
    result["meta"]["command"] = "python -m benchmarks.tool_rag.run " + " ".join(sys.argv[1:] if argv is None else argv)
    print(harness.format_summary(result))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
