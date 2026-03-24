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

# 시스템 의존성 설치 (빌드 도구)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# ---------------------------------------------------------------------------
# Stage 2: Application
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

# 런타임 시스템 의존성 (curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# deps 스테이지에서 설치된 Python 패키지 복사
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# 애플리케이션 코드 복사
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY db/ ./db/
# data 디렉토리 생성 후 설정 파일을 복사한다 (strategy_params.json은 data/ 내부에 위치한다)
RUN mkdir -p /app/data
COPY data/strategy_params.json ./data/strategy_params.json
COPY data/ticker_params.json ./data/ticker_params.json
COPY data/trading_principles.json ./data/trading_principles.json

# 비-root 사용자를 생성한다 (보안 강화)
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Docker 전용 환경변수
ENV DOCKER_MODE=1
ENV MLX_ENABLED=0
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 헬스체크 경로는 /api/system/health이다 (system_router prefix="/api/system")
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9501/api/system/health || exit 1

EXPOSE 9501

CMD ["python", "scripts/start_dashboard.py"]
