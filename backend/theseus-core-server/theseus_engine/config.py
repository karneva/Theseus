"""엔진 LLM 설정과 provider 라우팅.

엔진은 CLI/TUI/VSCode 확장과 Core 서버가 함께 쓰므로 `src.config`에 의존하지 않고
환경변수를 직접 읽습니다. 다만 LLM 클라이언트가 쓰는 base URL, timeout, 재시도 횟수,
출력 토큰 상한은 이 모듈 한 곳에서만 읽습니다.

`get_llm_settings()`는 호출할 때마다 환경변수를 다시 읽습니다. daemon/CLI가 실행 중에
`os.environ`을 바꾸는 경우가 있어 캐시하지 않습니다(읽는 비용은 무시할 만합니다).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_LLM_TIMEOUT_SECONDS = 120.0
DEFAULT_LLM_MAX_RETRIES = 3
DEFAULT_LLM_MAX_OUTPUT_TOKENS = 32768
DEFAULT_STREAM_MAX_AGENT_TURNS = 30

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_OLLAMA = "ollama"
PROVIDER_VLLM = "vllm"

# `provider/model` 형식의 명시적 접두사. google/은 기존 설정 호환용 별칭입니다.
_EXPLICIT_PREFIXES: dict[str, str] = {
    "ollama": PROVIDER_OLLAMA,
    "vllm": PROVIDER_VLLM,
    "anthropic": PROVIDER_ANTHROPIC,
    "openai": PROVIDER_OPENAI,
    "gemini": PROVIDER_GEMINI,
    "google": PROVIDER_GEMINI,
    "deepseek": PROVIDER_DEEPSEEK,
}


@dataclass(frozen=True)
class LLMSettings:
    ollama_base_url: str
    # OpenAI 클라이언트용 base URL. 비어 있으면 SDK 기본값(api.openai.com)을 씁니다.
    openai_base_url: str | None
    # vLLM은 OpenAI 호환 서버이므로 OPENAI_BASE_URL을 공유하고, 없으면 로컬 기본값을 씁니다.
    vllm_base_url: str
    gemini_base_url: str
    deepseek_base_url: str
    timeout_seconds: float
    max_retries: int
    max_output_tokens: int


@dataclass(frozen=True)
class ProviderRoute:
    """모델 문자열을 해석한 결과. model_id는 provider에 실제로 보낼 모델 id입니다."""

    provider: str
    model_id: str
    explicit: bool


def _env_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def get_llm_settings() -> LLMSettings:
    openai_base_url = _env_str("OPENAI_BASE_URL")
    return LLMSettings(
        ollama_base_url=_env_str("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL,
        openai_base_url=openai_base_url,
        vllm_base_url=openai_base_url or DEFAULT_VLLM_BASE_URL,
        gemini_base_url=_env_str("GEMINI_BASE_URL") or DEFAULT_GEMINI_BASE_URL,
        deepseek_base_url=_env_str("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL,
        timeout_seconds=_env_float("THESEUS_LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS),
        max_retries=_env_int("THESEUS_LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES, minimum=0),
        max_output_tokens=_env_int(
            "LLM_MAX_OUTPUT_TOKENS", DEFAULT_LLM_MAX_OUTPUT_TOKENS, minimum=1
        ),
    )


def llm_max_output_tokens() -> int:
    """PLAN/BUILD/repair/audit 등 LLM 호출의 출력 토큰 상한(LLM_MAX_OUTPUT_TOKENS)."""
    return get_llm_settings().max_output_tokens


def resolve_provider(model_name: str) -> ProviderRoute:
    """모델 문자열에서 provider를 결정합니다.

    1. `provider/model` 접두사가 알려진 provider면 그대로 따릅니다. 그래서
       `ollama/deepseek-r1`은 이름에 deepseek가 있어도 Ollama(OLLAMA_BASE_URL)로 갑니다.
    2. 접두사가 없을 때만 모델명의 부분 문자열(claude, gemini, deepseek)로 추정하고,
       어느 것도 아니면 OpenAI로 보냅니다.
    3. 알 수 없는 접두사(`meta-llama/...` 같은 HF 모델 id)는 잘라내지 않고 전체를 넘깁니다.
    """
    raw = (model_name or "").strip()
    lowered = raw.lower()

    if lowered == PROVIDER_VLLM:
        # 모델 id 없이 "vllm"만 주면 served model 자동 탐색에 맡깁니다.
        return ProviderRoute(provider=PROVIDER_VLLM, model_id=raw, explicit=True)

    prefix, sep, rest = raw.partition("/")
    if sep and prefix.lower() in _EXPLICIT_PREFIXES and rest:
        return ProviderRoute(
            provider=_EXPLICIT_PREFIXES[prefix.lower()], model_id=rest, explicit=True
        )

    if "claude" in lowered:
        provider = PROVIDER_ANTHROPIC
    elif "gemini" in lowered:
        provider = PROVIDER_GEMINI
    elif "deepseek" in lowered:
        provider = PROVIDER_DEEPSEEK
    else:
        provider = PROVIDER_OPENAI
    return ProviderRoute(provider=provider, model_id=raw, explicit=False)


def stream_max_agent_turns() -> int:
    """대화형 엔진의 최대 agent turn 수(CORE_STREAM_MAX_AGENT_TURNS, 기본 30)."""
    return _env_int("CORE_STREAM_MAX_AGENT_TURNS", DEFAULT_STREAM_MAX_AGENT_TURNS, minimum=1)


# ──────────────────────────────────────────────────────────────────────────────
# Tool RAG (theseus_engine/core/tool_rag) 설정
#
# 도구 검색 관련 환경변수는 이 함수 한 곳에서만 읽습니다. 값의 근거(dev 분할에서 고른 값)와
# 측정 결과는 docs/architecture/tool-rag.md에 있습니다. 임베딩 모델을 바꿀 때(예: 3단계 파인튜닝 모델)는
# THESEUS_EMBED_MODEL_DIR만 바꾸면 됩니다. 프리픽스·차원·풀링은 모델 디렉터리의 embedder.json에서 읽습니다.
# ──────────────────────────────────────────────────────────────────────────────

EMBED_BACKEND_ONNX = "onnx"
EMBED_BACKEND_SENTENCE_TRANSFORMERS = "sentence-transformers"
DEFAULT_EMBED_MODEL_DIR = "/opt/models/e5-small-int8"
DEFAULT_EMBED_MODEL_ID = "intfloat/multilingual-e5-small"
DEFAULT_EMBED_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_number(name: str, default: float, *, minimum: float) -> float:
    """0을 허용하는 실수 설정(예: BM25 가중치 0 = 끔). 잘못된 값이면 기본값."""
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    raw = _env_str(name)
    if raw is None:
        return default
    raw = raw.lower()
    return raw if raw in choices else default


def _theseus_data_dir() -> str:
    return _env_str("THESEUS_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".theseus")


def resolve_embed_model_dir() -> str:
    """ONNX 임베딩 모델 디렉터리. 환경변수 → 이미지 기본 경로 → 사용자 홈 순으로 찾습니다."""
    explicit = _env_str("THESEUS_EMBED_MODEL_DIR")
    if explicit:
        return explicit
    home_dir = os.path.join(os.path.expanduser("~"), ".theseus", "models", "e5-small-int8")
    for candidate in (DEFAULT_EMBED_MODEL_DIR, home_dir):
        if os.path.isfile(os.path.join(candidate, "model.onnx")):
            return candidate
    return DEFAULT_EMBED_MODEL_DIR


@dataclass(frozen=True)
class ToolRagSettings:
    enabled: bool
    server_enabled: bool
    embed_backend: str
    embed_model_dir: str
    embed_model_id: str
    embed_model_revision: str
    embed_threads: int
    embed_max_length: int
    calibration_file: str | None
    bm25_beta: float
    cost_budget: float
    rank_alpha: float
    max_candidates: int
    none_mode: str
    soft_keep: int
    small_set: int
    hook_budget: float
    hook_max_inject: int
    cache_dir: str | None
    feedback: str
    feedback_max_per_tool: int


def get_tool_rag_settings() -> ToolRagSettings:
    """Tool RAG 설정. LLM 설정과 마찬가지로 호출할 때마다 환경변수를 다시 읽습니다."""
    legacy_enabled = _env_bool("THESEUS_DYNAMIC_TOOL_RETRIEVAL", True)
    cache_raw = os.getenv("THESEUS_TOOL_RAG_CACHE_DIR")
    if cache_raw is None:
        cache_dir: str | None = os.path.join(_theseus_data_dir(), "tool_rag_cache")
    else:
        cache_dir = cache_raw.strip() or None  # 빈 값이면 디스크 캐시를 끕니다.
    return ToolRagSettings(
        enabled=_env_bool("THESEUS_TOOL_RAG_ENABLED", legacy_enabled),
        server_enabled=_env_bool("THESEUS_SERVER_TOOL_RAG", True),
        embed_backend=_env_choice(
            "THESEUS_EMBED_BACKEND",
            EMBED_BACKEND_ONNX,
            (EMBED_BACKEND_ONNX, EMBED_BACKEND_SENTENCE_TRANSFORMERS),
        ),
        embed_model_dir=resolve_embed_model_dir(),
        embed_model_id=_env_str("THESEUS_EMBED_MODEL_ID") or DEFAULT_EMBED_MODEL_ID,
        embed_model_revision=_env_str("THESEUS_EMBED_MODEL_REVISION") or DEFAULT_EMBED_MODEL_REVISION,
        embed_threads=_env_int("THESEUS_EMBED_THREADS", min(2, os.cpu_count() or 1), minimum=1),
        embed_max_length=_env_int("THESEUS_EMBED_MAX_LENGTH", 512, minimum=8),
        calibration_file=_env_str("THESEUS_TOOL_RAG_CALIBRATION_FILE"),
        bm25_beta=_env_number("THESEUS_TOOL_RAG_BM25_BETA", 0.10, minimum=0.0),
        cost_budget=_env_number("THESEUS_TOOL_RAG_COST_BUDGET", 700.0, minimum=0.0),
        rank_alpha=_env_number("THESEUS_TOOL_RAG_RANK_ALPHA", 1.0, minimum=0.0),
        max_candidates=_env_int("THESEUS_TOOL_RAG_MAX_CANDIDATES", 12, minimum=1),
        none_mode=_env_choice("THESEUS_TOOL_RAG_NONE_MODE", "soft", ("off", "soft")),
        soft_keep=_env_int("THESEUS_TOOL_RAG_SOFT_KEEP", 3, minimum=0),
        small_set=_env_int("THESEUS_TOOL_RAG_SMALL_SET", 12, minimum=0),
        hook_budget=_env_number("THESEUS_TOOL_RAG_HOOK_BUDGET", 400.0, minimum=0.0),
        hook_max_inject=_env_int("THESEUS_TOOL_RAG_HOOK_MAX_INJECT_PER_SESSION", 6, minimum=0),
        cache_dir=cache_dir,
        feedback=_env_choice("THESEUS_TOOL_RAG_FEEDBACK", "cli", ("off", "cli")),
        feedback_max_per_tool=_env_int("THESEUS_TOOL_RAG_FEEDBACK_MAX_PER_TOOL", 5, minimum=0),
    )
