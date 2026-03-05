#!/bin/bash
#
# AI Auto-Trading System V2 - Always-On Server Script
#
# 서버를 항상 실행 상태로 유지하는 스크립트이다.
# Docker 서비스(PostgreSQL + Redis) 확인 후 python3 -m src.main을 실행한다.
# 매매 스케줄은 auto_trading.sh가 API로 제어한다. 이 스크립트는 서버 수명만 관리한다.
# LaunchAgent(com.trading.server.plist)에서 KeepAlive=true로 호출한다.
#

set -euo pipefail

# ============================================
# 설정
# ============================================
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"
LOG_DIR="$HOME/Library/Logs/trading"
PID_FILE="$LOG_DIR/server.pid"
PORT=9501

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SERVER] $1" | tee -a "$LOG_DIR/server.log"
}

# ============================================
# 네트워크 연결 확인
# ============================================
wait_for_network() {
    local max_retries=30
    local retry=0
    log "네트워크 연결 확인 중..."

    while [ $retry -lt $max_retries ]; do
        if curl -s --max-time 5 -o /dev/null https://www.google.com 2>/dev/null; then
            log "네트워크 연결 확인 완료"
            return 0
        fi
        retry=$((retry + 1))
        log "네트워크 대기 중... ($retry/$max_retries)"
        sleep 10
    done

    log "ERROR: 네트워크 연결 실패"
    return 1
}

# ============================================
# Docker 서비스 확인 및 시작
# ============================================
start_docker_services() {
    log "Docker 서비스 확인 중..."

    # Docker Desktop 실행 확인
    if ! docker info > /dev/null 2>&1; then
        log "Docker Desktop 시작 중..."
        open -a Docker
        local retry=0
        while [ $retry -lt 30 ]; do
            if docker info > /dev/null 2>&1; then
                log "Docker Desktop 시작 완료"
                break
            fi
            retry=$((retry + 1))
            sleep 5
        done
        if [ $retry -ge 30 ]; then
            log "ERROR: Docker Desktop 시작 실패"
            return 1
        fi
    fi

    # docker compose 서비스 시작 (PostgreSQL + Redis)
    cd "$PROJECT_ROOT"
    if ! docker compose ps 2>/dev/null | grep -q "Up"; then
        log "Docker 컨테이너 시작 중 (PostgreSQL, Redis)..."
        docker compose up -d
        sleep 10
        log "Docker 컨테이너 시작 완료"
    else
        log "Docker 컨테이너 이미 실행 중"
    fi

    # 헬스체크
    local retry=0
    while [ $retry -lt 10 ]; do
        if docker compose ps | grep -q "healthy"; then
            log "Docker 서비스 헬스체크 통과"
            return 0
        fi
        retry=$((retry + 1))
        sleep 3
    done

    log "WARNING: Docker 헬스체크 타임아웃, 계속 진행한다"
    return 0
}

# ============================================
# 포트 정리 (9501)
# ============================================
cleanup_port() {
    local port_pid
    port_pid=$(lsof -ti :$PORT 2>/dev/null || true)
    if [ -n "$port_pid" ]; then
        log "포트 $PORT 사용 중 (PID: $port_pid). 정리 중..."
        kill -SIGTERM $port_pid 2>/dev/null || true
        sleep 3
        if lsof -ti :$PORT > /dev/null 2>&1; then
            local stale_pid
            stale_pid=$(lsof -ti :$PORT 2>/dev/null || true)
            log "포트 $PORT 강제 종료 (PID: $stale_pid)..."
            kill -SIGKILL $stale_pid 2>/dev/null || true
            sleep 1
        fi
        log "포트 $PORT 정리 완료"
    fi
}

# ============================================
# 포트 해제 대기
# ============================================
wait_for_port_free() {
    local max_attempts=15
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        # lsof로 프로세스 점유 확인 + python으로 실제 바인드 테스트
        if ! lsof -ti :$PORT > /dev/null 2>&1; then
            if python3 -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('0.0.0.0', $PORT))
    s.close()
    sys.exit(0)
except OSError:
    s.close()
    sys.exit(1)
" 2>/dev/null; then
                log "포트 $PORT 해제 확인 완료 (바인드 테스트 통과)"
                return 0
            fi
        fi
        attempt=$((attempt + 1))
        log "포트 $PORT 해제 대기 중... ($attempt/$max_attempts)"
        sleep 2
    done
    log "WARNING: 포트 $PORT 여전히 사용 중. 계속 진행한다."
    return 0
}

# ============================================
# 클린업 (SIGTERM/SIGINT 수신 시)
# ============================================
cleanup() {
    log "서버 종료 신호 수신. 정리 중..."
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill -SIGTERM "$pid" 2>/dev/null
            # 서버가 graceful shutdown 할 시간을 준다
            sleep 15
            if kill -0 "$pid" 2>/dev/null; then
                kill -SIGKILL "$pid" 2>/dev/null
            fi
        fi
        rm -f "$PID_FILE"
    fi
    log "서버 종료 완료"
}

trap cleanup EXIT SIGTERM SIGINT

# ============================================
# 메인 실행
# ============================================
main() {
    log "=========================================="
    log "AI Auto-Trading System V2 - Server Start"
    log "=========================================="

    # 슬립 방지 (caffeinate) -- 서버가 항상 실행되어야 하므로 sleep을 방지한다
    caffeinate -i -w $$ &
    log "caffeinate 활성화 (PID: $!, 부모 PID: $$)"

    # 네트워크 확인
    wait_for_network || exit 1

    # Docker 시작
    start_docker_services || exit 1

    # 가상환경 활성화
    cd "$PROJECT_ROOT"
    if [ -d "$VENV_PATH" ]; then
        source "$VENV_PATH/bin/activate"
        log "가상환경 활성화: $VENV_PATH"
    else
        log "ERROR: 가상환경을 찾을 수 없다: $VENV_PATH"
        exit 1
    fi

    # CLAUDECODE 환경변수 제거 (중첩 세션 방지)
    unset CLAUDECODE
    unset CLAUDE_CODE

    # 포트 사전 정리
    cleanup_port
    wait_for_port_free

    # 환경변수 설정
    export PYTHONPATH="$PROJECT_ROOT"
    export PYTHONUNBUFFERED=1

    # 서버 시작 -- 종료 시간 제한 없이 영구 실행한다
    log "서버 시작 중 (포트: $PORT)..."
    python3 -m src.main \
        >> "$LOG_DIR/server_stdout.log" \
        2>> "$LOG_DIR/server_stderr.log" &
    local server_pid=$!
    echo "$server_pid" > "$PID_FILE"
    log "서버 PID: $server_pid"

    # 서버 프로세스가 종료될 때까지 대기한다
    # KeepAlive=true이므로 LaunchAgent가 비정상 종료 시 재시작한다
    wait "$server_pid" || true
    local exit_code=$?

    log "서버 프로세스 종료 (exit code: $exit_code)"
    rm -f "$PID_FILE"

    # exit code를 그대로 전달한다 -- LaunchAgent KeepAlive가 재시작 여부를 결정한다
    exit $exit_code
}

main "$@"
