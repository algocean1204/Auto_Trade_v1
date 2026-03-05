# =============================================================================
# AI Trading System V2 - FastAPI Dashboard Server
#
# Multi-stage build for optimized image size.
# MLX/ChromaDB/Embedding 패키지는 제외 (Apple Silicon 전용 또는 대시보드에 불필요).
# DOCKER_MODE=1 환경변수로 Docker 전용 동작을 활성화한다.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Dependencies (cached layer)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS deps

WORKDIR /app

# 시스템 의존성 설치 (psycopg2-binary 빌드에 필요)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# ---------------------------------------------------------------------------
# Stage 2: Application
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

# 런타임 시스템 의존성 (libpq for psycopg2)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# deps 스테이지에서 설치된 Python 패키지 복사
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# 애플리케이션 코드 복사
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY db/ ./db/
COPY strategy_params.json ./strategy_params.json

# data 디렉토리 생성 (런타임에 볼륨 마운트됨)
RUN mkdir -p /app/data

# Docker 전용 환경변수
ENV DOCKER_MODE=1
ENV MLX_ENABLED=0
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9500/health || exit 1

EXPOSE 9500

CMD ["python", "scripts/start_dashboard.py"]
