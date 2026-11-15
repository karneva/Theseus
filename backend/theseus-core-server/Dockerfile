# syntax=docker/dockerfile:1
#
# Theseus Core Server 이미지.
# - builder: /opt/venv 가상환경에 의존성을 설치합니다. 컴파일러는 이 단계에만 둡니다.
# - runtime: venv와 소스만 복사하고 non-root(appuser)로 실행합니다.

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

# sentence-transformers가 끌어오는 torch를 CPU 전용 인덱스에서 먼저 설치합니다.
# 이렇게 해야 이어지는 requirements 설치가 이미 만족된 torch를 그대로 쓰고,
# PyPI 기본 Linux 휠(CUDA + nvidia-* 수 GB)을 내려받지 않습니다.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --index-url "${TORCH_INDEX_URL}" "torch<3"

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && pip check

# ── 런타임 스테이지 ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ARG APP_UID=999
ARG APP_GID=999

# 보안: non-root 사용자로 실행합니다.
RUN groupadd --system --gid "${APP_GID}" appuser \
    && useradd --system --uid "${APP_UID}" --gid appuser -m -d /home/appuser appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# HF_HOME: 임베딩 모델(sentence-transformers) 캐시 경로입니다. 컨테이너를 다시 만들 때
# 재다운로드하지 않도록 compose에서 이 경로에 named volume을 붙입니다.
# THESEUS_DATA_DIR: 생성 Tool 등 런타임 데이터 경로로, 역시 volume 대상입니다.
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/home/appuser \
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
