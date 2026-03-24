#!/bin/bash
#
# AI Auto-Trading System V2 - Always-On Server Script
#
# 서버를 항상 실행 상태로 유지하는 스크립트이다.
# SQLite + InMemoryCache 모드이므로 외부 DB/캐시 서비스 없이 python3 -m src.main을 실행한다.
# 매매 스케줄은 auto_trading.sh가 API로 제어한다. 이 스크립트는 서버 수명만 관리한다.
# LaunchAgent(com.trading.server.plist)에서 KeepAlive=true로 호출한다.
#

set -euo pipefail

# ============================================
# 설정
# ============================================
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"
# macOS: ~/Library/Logs/trading, Linux: 프로젝트 루트 하위 logs/ 를 사용한다
if [ -d "$HOME/Library" ]; then
    LOG_DIR="$HOME/Library/Logs/trading"
else
    LOG_DIR="$PROJECT_ROOT/logs"
fi
PID_FILE="$LOG_DIR/server.pid"
PORT_FILE="$PROJECT_ROOT/data/server_port.txt"
DEFAULT_PORT=9501

# 포트 파일에서 현재 서버 포트를 읽는다. 파일이 없으면 기본값을 반환한다.
read_port() {
    if [ -f "$PORT_FILE" ]; then
        local port
        port=$(cat "$PORT_FILE" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$port" ] && [ "$port" -ge 9501 ] 2>/dev/null && [ "$port" -le 9505 ] 2>/dev/null; then
            echo "$port"
            return
        fi
    fi
    echo "$DEFAULT_PORT"
}

PORT=$(read_port)

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

# 로그 로테이션 -- 지정 파일이 10MB 초과 시 .1 → .2 → .3으로 이동한다 (최대 3개 보관)
rotate_log() {
    local log_file="$1"
    local max_size=$((10 * 1024 * 1024))  # 10MB

    if [ ! -f "$log_file" ]; then
        return 0
    fi

    local file_size
    # macOS: stat -f%z, Linux: stat -c%s -- 양쪽 모두 지원한다
    file_size=$(stat -f%z "$log_file" 2>/dev/null || stat -c%s "$log_file" 2>/dev/null || echo "0")

    if [ "$file_size" -gt "$max_size" ]; then
        [ -f "${log_file}.2" ] && mv -f "${log_file}.2" "${log_file}.3"
        [ -f "${log_file}.1" ] && mv -f "${log_file}.1" "${log_file}.2"
        mv -f "$log_file" "${log_file}.1"
    fi
}

# 스크립트 시작 시 로그 로테이션을 수행한다
rotate_log "$LOG_DIR/server.log"
rotate_log "$LOG_DIR/server_stdout.log"
rotate_log "$LOG_DIR/server_stderr.log"

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
# Docker 서비스 확인 (SQLite + InMemoryCache 전환으로 런타임에는 불필요)
# migration 프로필 서비스만 존재하므로 docker compose up -d는 실행하지 않는다.
# ============================================
start_docker_services() {
    log "SQLite + InMemoryCache 모드 -- Docker 서비스 불필요 (건너뜀)"
    return 0
}

# ============================================
# 포트 정리 (서버가 사용 중인 포트를 해제한다)
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
# 중복 실행 방지 플래그이다. SIGTERM→cleanup→EXIT→cleanup 이중 호출을 차단한다.
_CLEANUP_DONE=0

cleanup() {
    if [ "$_CLEANUP_DONE" -eq 1 ]; then
        return
    fi
    _CLEANUP_DONE=1

    log "서버 종료 신호 수신. 정리 중..."
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill -SIGTERM "$pid" 2>/dev/null
            # 서버가 graceful shutdown 할 시간을 준다
            local waited=0
            while [ "$waited" -lt 15 ] && kill -0 "$pid" 2>/dev/null; do
                sleep 1
                waited=$((waited + 1))
            done
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

    # 슬립 방지 (caffeinate) -- 서버가 항상 실행되어야 하므로 sleep을 방지한다 (macOS 전용)
    if command -v caffeinate >/dev/null 2>&1; then
        caffeinate -i -w $$ &
        log "caffeinate 활성화 (PID: $!, 부모 PID: $$)"
    else
        log "caffeinate 미설치 (macOS 이외 환경) -- 슬립 방지 건너뜀"
    fi

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

    # 포트 사전 정리 (이전 세션의 포트를 해제한다)
    cleanup_port
    wait_for_port_free

    # 환경변수 설정
    export PYTHONPATH="$PROJECT_ROOT"
    export PYTHONUNBUFFERED=1

    # 서버 시작 -- 동적 포트 선택 (9501-9505), 종료 시간 제한 없이 영구 실행한다
    log "서버 시작 중 (초기 포트: $PORT, 동적 선택 가능)..."
    python3 -m src.main \
        >> "$LOG_DIR/server_stdout.log" \
        2>> "$LOG_DIR/server_stderr.log" &
    local server_pid=$!
    echo "$server_pid" > "$PID_FILE"
    log "서버 PID: $server_pid"

    # 서버가 포트 파일을 기록할 때까지 잠시 대기한 후 실제 포트를 갱신한다
    sleep 5
    PORT=$(read_port)
    log "실제 서버 포트: $PORT (포트 파일: $PORT_FILE)"

    # 서버 프로세스가 종료될 때까지 대기한다
    # KeepAlive=true이므로 LaunchAgent가 비정상 종료 시 재시작한다
    # wait가 시그널로 인터럽트되면 128+signal을 반환한다
    local exit_code=0
    wait "$server_pid" || exit_code=$?

    log "서버 프로세스 종료 (exit code: $exit_code)"
    rm -f "$PID_FILE"

    # exit code를 그대로 전달한다 -- LaunchAgent KeepAlive가 재시작 여부를 결정한다
    exit $exit_code
}

main "$@"
