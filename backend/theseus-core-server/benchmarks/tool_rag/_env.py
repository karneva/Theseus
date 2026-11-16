"""평가 환경 고정. theseus_engine을 import하기 전에 반드시 먼저 실행되어야 합니다.

`benchmarks.tool_rag` 패키지를 import하면 자동으로 실행됩니다. 하는 일:
  * 바이트코드를 쓰지 않습니다(저장소/스크래치 폴더 오염 방지).
  * 피드백 로그(tool_usage.jsonl)를 빈 임시 디렉터리로 돌립니다.
    -> few-shot passage가 정확히 TOOL_EXAMPLE_QUERIES + tool.example_queries 가 되어
       개발자의 ~/.theseus 사용 이력과 무관하게 결정적입니다.
  * 고정 리비전의 임베딩 모델이 HF 캐시에 있으면 HF를 오프라인으로 돌려
    상류의 새 리비전이 조용히 섞이지 않게 합니다.
  * src.* (서버 레지스트리) import에 필요한 최소 설정값을 채웁니다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]  # .../backend/theseus-core-server

MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"  # 동결 베이스라인이 측정한 리비전

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

# 피드백 로그는 항상 빈 디렉터리(사용자 환경변수보다 우선). 프로세스마다 새로 만듭니다.
EMPTY_FEEDBACK_DIR = Path(tempfile.mkdtemp(prefix="toolrag-empty-feedback-"))
os.environ["THESEUS_DATA_DIR"] = str(EMPTY_FEEDBACK_DIR)

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("ALLOWED_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault("THESEUS_LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")


def _hf_home() -> Path:
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"])
    return Path.home() / ".cache" / "huggingface"


PINNED_SNAPSHOT = (
    _hf_home() / "hub" / "models--intfloat--multilingual-e5-small" / "snapshots" / MODEL_REVISION
)


def cached_main_revision() -> str | None:
    """오프라인 모드에서 SentenceTransformer가 실제로 고르는 리비전(HF 캐시의 refs/main)."""
    ref = PINNED_SNAPSHOT.parents[1] / "refs" / "main"
    try:
        return ref.read_text(encoding="utf-8").strip()
    except OSError:
        return None


if (PINNED_SNAPSHOT / "model.safetensors").exists():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
# v2 로거(theseus_engine/core/tool_usage_logger.py)는 호출할 때마다 THESEUS_DATA_DIR을 읽으므로
# 실험자가 하네스보다 먼저 theseus_engine을 import했어도 위 설정이 적용됩니다.
# v2 어댑터(v2.py)는 여기에 더해 THESEUS_TOOL_RAG_FEEDBACK=off로 피드백 병합 자체를 끕니다.
