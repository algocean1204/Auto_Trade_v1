#!/bin/bash
#
# API 서버를 호스트에서 직접 실행한다.
#
# SQLite + InMemoryCache 모드이므로 Docker 서비스가 불필요하다.
# Claude Code local CLI 접근을 위해 호스트 .venv에서 기동한다.
#
# 사용법:
#   bash scripts/start_api.sh
#   # 포트 변경:
#   API_PORT=8080 bash scripts/start_api.sh
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
# SQLite + InMemoryCache 모드 -- Docker 불필요
# ============================================
echo "SQLite + InMemoryCache 모드 -- Docker 서비스 불필요 (건너뜀)"

# ============================================
# CLAUDECODE 환경변수 제거 (중첩 세션 방지)
# ============================================
unset CLAUDECODE
unset CLAUDE_CODE

# ============================================
# API 서버 포트 결정
# ============================================
PORT="${API_PORT:-9501}"

# ============================================
# API 서버 시작
# ============================================
echo ""
echo "============================================"
echo "  AI Trading System V2 - API Server (Host)"
echo "  Port : $PORT"
echo "  DB   : SQLite (data/trading.db)"
echo "  Cache: InMemoryCache"
echo "  Claude Mode: ${CLAUDE_MODE:-local}"
echo "============================================"
echo ""

# api_server.py에 모듈 레벨 app 객체가 없으므로 (create_app 팩토리 패턴)
# 항상 start_dashboard.py를 통해 시작한다 (DI 초기화 포함)
exec python scripts/start_dashboard.py
