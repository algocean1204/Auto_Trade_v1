#!/bin/bash
#
# API 서버를 호스트에서 직접 실행한다 (Claude CLI 접근을 위해).
#
# Docker는 PostgreSQL + Redis만 담당하고, FastAPI는 호스트 .venv에서 기동한다.
# 이렇게 해야 Claude Code local CLI가 ~/.local/bin/claude 경로로
# 정상적으로 접근된다.
#
# 사용법:
#   bash scripts/start_api.sh
#   # 포트 변경:
#   API_PORT=8080 bash scripts/start_api.sh
#   # 자동 재로드 비활성화 (프로덕션):
#   NO_RELOAD=1 bash scripts/start_api.sh
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"

cd "$PROJECT_ROOT"

# ============================================
# 가상환경 확인
# ============================================
if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: 가상환경을 찾을 수 없습니다: $VENV_PATH"
    echo "       python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source "$VENV_PATH/bin/activate"

# ============================================
# .env 로드 확인
# ============================================
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "WARNING: .env 파일이 없습니다. 환경변수를 직접 설정하거나 .env 파일을 만드세요."
fi

# ============================================
# Docker DB + Redis 상태 확인 및 시작
# ============================================
if docker info > /dev/null 2>&1; then
    running=$(docker compose ps --services --filter status=running 2>/dev/null || true)
    if ! echo "$running" | grep -q "postgres"; then
        echo "PostgreSQL이 실행되지 않았습니다. Docker 서비스를 시작합니다..."
        docker compose up -d
        echo "Docker 서비스 시작 완료. 3초 대기..."
        sleep 3
    else
        echo "Docker 서비스 실행 중 (postgres + redis 확인됨)"
    fi
else
    echo "WARNING: Docker를 찾을 수 없습니다. DB 서비스가 별도로 실행 중인지 확인하세요."
fi

# ============================================
# CLAUDECODE 환경변수 제거 (중첩 세션 방지)
# ============================================
unset CLAUDECODE
unset CLAUDE_CODE

# ============================================
# API 서버 포트 결정
# ============================================
PORT="${API_PORT:-8000}"

# ============================================
# API 서버 시작
# ============================================
echo ""
echo "============================================"
echo "  AI Trading System V2 - API Server (Host)"
echo "  Port : $PORT"
echo "  DB   : ${DB_HOST:-localhost}:${DB_PORT:-5432}"
echo "  Redis: ${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}"
echo "  Claude Mode: ${CLAUDE_MODE:-local}"
echo "============================================"
echo ""

if [ "${NO_RELOAD:-0}" = "1" ]; then
    # 프로덕션 모드: 자동 재로드 없이 실행
    exec python -m uvicorn src.monitoring.api_server:app \
        --host 0.0.0.0 \
        --port "$PORT"
else
    # 개발 모드: 파일 변경 시 자동 재로드
    exec python scripts/start_dashboard.py
fi
