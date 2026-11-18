# syntax=docker/dockerfile:1
#
# Theseus Core Server 이미지.
# - builder: /opt/venv 가상환경에 의존성을 설치합니다. 컴파일러는 이 단계에만 둡니다.
# - model  : Tool RAG 임베딩 모델(multilingual-e5-small ONNX int8)을 빌드 시점에 만들고 sha256을 검증합니다.
# - runtime: venv, 모델, 소스만 복사하고 non-root(appuser)로 실행합니다. 런타임에 모델을 내려받지 않습니다.

# ── 빌드 스테이지 ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# 휠이 없는 패키지가 섞일 때를 대비한 빌드 도구입니다. 런타임 이미지에는 들어가지 않습니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# torch는 설치하지 않습니다. Tool RAG 임베딩은 onnxruntime + sentencepiece로 돕니다.
# (sentence-transformers가 필요한 선택 기능은 requirements-torch.txt 참고)
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && pip check

# ── 모델 스테이지 ─────────────────────────────────────────────────────────────
# 고정 리비전의 공식 ONNX(fp32)를 받아 동적 int8로 양자화합니다. 양자화 peak 메모리가 약 2.4 GB라서
# 3.8 GB 서버의 런타임이 아니라 빌드 단계에서만 합니다. onnx/onnxruntime 버전을 고정해야 결과 파일이
# 바이트 단위로 같아지고(sha256 검증), 동봉한 none 판정 보정값(theseus_engine/core/tool_rag/data)이 적용됩니다.
FROM python:3.11-slim AS model

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

ARG TOOL_RAG_ONNX_VERSION=1.23.2
ARG TOOL_RAG_ORT_VERSION=1.32.0
ARG TOOL_RAG_HF_HUB_VERSION=2.4.0
RUN pip install "onnx==${TOOL_RAG_ONNX_VERSION}" "onnxruntime==${TOOL_RAG_ORT_VERSION}" \
    "huggingface-hub==${TOOL_RAG_HF_HUB_VERSION}"

COPY scripts/provision_tool_rag_model.py /build/provision_tool_rag_model.py
RUN python /build/provision_tool_rag_model.py --out /opt/models/e5-small-int8 \
    && rm -rf /root/.cache/huggingface

# ── 런타임 스테이지 ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ARG APP_UID=999
ARG APP_GID=999

# 보안: non-root 사용자로 실행합니다.
RUN groupadd --system --gid "${APP_GID}" appuser \
    && useradd --system --uid "${APP_UID}" --gid appuser -m -d /home/appuser appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# Tool RAG 모델(model.onnx 약 113 MiB, sentencepiece.bpe.model, embedder.json). 읽기 전용으로 둡니다.
COPY --from=model /opt/models/e5-small-int8 /opt/models/e5-small-int8

# THESEUS_EMBED_MODEL_DIR: Tool RAG 임베딩 모델 디렉터리. 파인튜닝 모델로 바꿀 때 이 경로만 바꿉니다.
# THESEUS_TOOL_RAG_FEEDBACK=off: 서버는 사용자 질의를 few-shot으로 쌓지 않습니다(멀티테넌트 격리).
# HF_HUB_OFFLINE=1: Core는 런타임에 Hugging Face로 나가지 않습니다.
# HF_HOME: 선택 기능(엔진 RAG의 sentence-transformers, requirements-torch.txt)용 캐시 경로입니다.
# THESEUS_DATA_DIR: 생성 Tool, Tool RAG 벡터 캐시 등 런타임 데이터 경로로, volume 대상입니다.
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/home/appuser \
    THESEUS_EMBED_MODEL_DIR=/opt/models/e5-small-int8 \
    THESEUS_TOOL_RAG_FEEDBACK=off \
    HF_HUB_OFFLINE=1 \
    HF_HOME=/home/appuser/.cache/huggingface \
    THESEUS_DATA_DIR=/home/appuser/.theseus/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8086

RUN mkdir -p "${HF_HOME}" "${THESEUS_DATA_DIR}" /tmp/theseus-sandbox-shared \
    && chown -R appuser:appuser /home/appuser /tmp/theseus-sandbox-shared

COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser theseus_engine/ ./theseus_engine/
RUN python -m compileall -q src theseus_engine

USER appuser

EXPOSE 8086

# /health는 인증 없이 status만 반환하는 liveness 엔드포인트입니다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8086'), timeout=4)" || exit 1

CMD ["sh", "-c", "exec python -m uvicorn src.main:app --host 0.0.0.0 --port \"${PORT:-8086}\" --workers 1"]
