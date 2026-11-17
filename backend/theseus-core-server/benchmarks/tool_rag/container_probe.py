"""Core 이미지 안에서 'import src.main → 첫 검색 → 웜 검색'의 프로세스 RSS와 시간을 잽니다(하네스와 별개).

    docker run --rm --cpus=2 --memory=1.5g -e PYTHONPATH=/app \
      -v <repo>/backend/theseus-core-server/benchmarks/tool_rag:/probe:ro \
      theseus-core:<tag> python /probe/container_probe.py

v2 이미지(theseus_engine.core.tool_rag가 있음)는 retrieve_sync, v1 이미지(torch)는 ToolRetriever.retrieve_top_k를 부릅니다.
v1 이미지는 모델을 런타임에 받으므로 HF 캐시를 -v <hf_home>:/hf:ro -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 로 붙입니다.
first_retrieval_s에는 모델 로드와 인덱스 구축이 들어 있습니다. 출력은 JSON 한 줄입니다.
"""

import asyncio
import json
import sys
import time

import psutil

QUERIES = ("웹에서 최신 파이썬 릴리스 노트 검색해줘", "백그라운드 작업 로그 보여줘")


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 2**20


def main() -> None:
    t0 = time.perf_counter()
    import src.main  # noqa: F401  (서버 모듈 그래프 전체)

    out = {"rss_after_import_src_main_mb": round(rss_mb(), 1), "import_s": round(time.perf_counter() - t0, 2)}
    from theseus_engine.tools.core import ALL_CORE_TOOLS
    from theseus_engine.tools.core.base_tools import ToolRegistry

    reg = ToolRegistry()
    for cls in ALL_CORE_TOOLS:
        reg.register(cls())
    names = [t.name for t in reg.list_tools()]
    try:
        from theseus_engine.core.tool_rag import get_tool_retriever

        retr = get_tool_retriever()
        run = lambda q: retr.retrieve_sync(q, reg, candidates=names).names  # noqa: E731
        out["impl"] = "v2"
        out["threads"] = retr.settings.embed_threads
    except ImportError:
        from theseus_engine.core.tool_retriever import ToolRetriever

        run = lambda q: [t.name for t in asyncio.run(ToolRetriever(reg).retrieve_top_k(q, reg, k=8))]  # noqa: E731
        out["impl"] = "v1"
    t1 = time.perf_counter()
    sent = run(QUERIES[0])
    out["first_retrieval_s"] = round(time.perf_counter() - t1, 2)
    t2 = time.perf_counter()
    run(QUERIES[1])
    out["warm_retrieval_ms"] = round((time.perf_counter() - t2) * 1000, 1)
    out["rss_after_retrieval_mb"] = round(rss_mb(), 1)
    out["n_sent"] = len(sent)
    out["torch_imported"] = "torch" in sys.modules
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
