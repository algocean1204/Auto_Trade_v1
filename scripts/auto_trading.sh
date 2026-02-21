#!/bin/bash
#
# AI Auto-Trading System V2 - Automated Night Trading Script
#
# 23:00 KST ~ 06:30 KST 자동매매 실행 스크립트.
# LaunchAgent에서 23:00에 시작, 06:30에 종료한다.
# 네트워크 연결 확인 후 Docker 서비스 및 트레이딩 시스템을 기동한다.
#

set -euo pipefail

# ============================================
# 설정
# ============================================
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"
LOG_DIR="$HOME/Library/Logs/trading"
PID_FILE="$LOG_DIR/trading.pid"
STOP_HOUR=6
STOP_MINUTE=30
MAX_RESTARTS=10
STABLE_THRESHOLD=300  # 5분(300초) 이상 생존하면 안정 판정

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_DIR/auto_trading.log"
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

    log "ERROR: 네트워크 연결 실패. 종료합니다."
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

    # docker compose 서비스 시작 (PostgreSQL + Redis만 실행, API 서버는 호스트에서 실행)
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

    log "WARNING: Docker 헬스체크 타임아웃, 계속 진행"
    return 0
}

# ============================================
# 종료 시간 확인
# ============================================
should_stop() {
    local current_hour=$(date '+%H' | sed 's/^0//')
    local current_minute=$(date '+%M' | sed 's/^0//')

    # 야간 세션은 23:00 ~ 06:30 (자정을 넘김)
    # 종료 조건: 07시 이상이거나, 06시 30분 이상일 때 (단, 23시~자정은 실행 중)
    # 즉, 현재 시각이 STOP_HOUR:STOP_MINUTE 이후이면서 23시 이전일 때만 종료
    if [ "$current_hour" -ge 23 ] || [ "$current_hour" -lt $STOP_HOUR ]; then
        # 23:00~05:59 → 실행 중
        return 1
    elif [ "$current_hour" -eq $STOP_HOUR ] && [ "$current_minute" -lt $STOP_MINUTE ]; then
        # 06:00~06:29 → 실행 중
        return 1
    fi

    # 06:30 이후 ~ 22:59 → 종료
    return 0
}

# ============================================
# 포트 9500 정리
# ============================================
cleanup_port_9500() {
    local port_pid
    port_pid=$(lsof -ti :9500 2>/dev/null || true)
    if [ -n "$port_pid" ]; then
        log "포트 9500 사용 중 (PID: $port_pid). 정리 중..."
        kill -SIGTERM "$port_pid" 2>/dev/null || true
        sleep 3
        if lsof -ti :9500 > /dev/null 2>&1; then
            local stale_pid
            stale_pid=$(lsof -ti :9500 2>/dev/null || true)
            log "포트 9500 강제 종료 (PID: $stale_pid)..."
            kill -SIGKILL "$stale_pid" 2>/dev/null || true
        fi
        log "포트 9500 정리 완료"
    fi
}

# ============================================
# 포트 9500 해제 대기
# ============================================
wait_for_port_9500_free() {
    local max_attempts=10
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if ! lsof -ti :9500 > /dev/null 2>&1; then
            log "포트 9500 해제 확인 완료"
            return 0
        fi
        attempt=$((attempt + 1))
        log "포트 9500 해제 대기 중... ($attempt/$max_attempts)"
        sleep 1
    done
    log "WARNING: 포트 9500이 여전히 사용 중입니다. 계속 진행합니다."
    return 0
}

# ============================================
# 클린업
# ============================================
cleanup() {
    log "트레이딩 시스템 종료 중..."
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill -SIGTERM "$pid" 2>/dev/null
            sleep 15
            kill -0 "$pid" 2>/dev/null && kill -SIGKILL "$pid" 2>/dev/null
        fi
        rm -f "$PID_FILE"
    fi
    log "트레이딩 시스템 종료 완료"
}

trap cleanup EXIT SIGTERM SIGINT

# ============================================
# 메인 실행
# ============================================
main() {
    log "=========================================="
    log "AI Auto-Trading System V2 - Night Session"
    log "=========================================="

    # 슬립 방지 (백그라운드) - macOS Sequoia TCC 정책 우회
    caffeinate -i -w $$ &
    log "caffeinate 백그라운드 실행 (PID: $!, 부모 PID: $$)"

    # 이미 종료 시간이면 바로 종료
    if should_stop; then
        log "현재 시간이 종료 시간(${STOP_HOUR}:${STOP_MINUTE}) 이후입니다. 종료합니다."
        exit 0
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
        log "ERROR: 가상환경을 찾을 수 없습니다: $VENV_PATH"
        exit 1
    fi

    # CLAUDECODE 환경변수 제거 (중첩 세션 방지)
    unset CLAUDECODE
    unset CLAUDE_CODE

    # 포트 9500 사전 정리
    cleanup_port_9500

    # 트레이딩 시스템 실행
    log "트레이딩 시스템 시작..."
    PYTHONUNBUFFERED=1 python3 -m src.main \
        >> "$LOG_DIR/trading_stdout.log" \
        2>> "$LOG_DIR/trading_stderr.log" &
    local trading_pid=$!
    echo "$trading_pid" > "$PID_FILE"
    log "트레이딩 시스템 PID: $trading_pid"

    # 재시작 카운터 및 시간 추적
    local restart_count=0
    local last_start_time
    last_start_time=$(date +%s)

    # 종료 시간까지 대기하면서 프로세스 감시
    while true; do
        if should_stop; then
            log "종료 시간(${STOP_HOUR}:${STOP_MINUTE}) 도달. 시스템을 종료합니다."
            break
        fi

        # 트레이딩 프로세스가 비정상 종료된 경우 재시작
        if ! kill -0 "$trading_pid" 2>/dev/null; then
            local now
            now=$(date +%s)
            local uptime=$((now - last_start_time))

            if [ "$uptime" -ge "$STABLE_THRESHOLD" ]; then
                # 5분 이상 생존했으면 안정적이었음 -> 카운터 리셋
                restart_count=0
                log "이전 프로세스가 ${uptime}초 동안 안정 실행됨. 재시작 카운터 리셋."
            fi

            restart_count=$((restart_count + 1))

            if [ "$restart_count" -gt "$MAX_RESTARTS" ]; then
                log "ERROR: 연속 재시작 횟수 초과 (${restart_count}/${MAX_RESTARTS}). 무한 루프 방지를 위해 종료합니다."
                log "ERROR: 최근 프로세스 생존 시간: ${uptime}초. 수동 점검이 필요합니다."
                exit 1
            fi

            log "WARNING: 트레이딩 프로세스가 종료되었습니다 (생존: ${uptime}초). 재시작 중... (${restart_count}/${MAX_RESTARTS})"
            cleanup_port_9500
            wait_for_port_9500_free
            PYTHONUNBUFFERED=1 python3 -m src.main \
                >> "$LOG_DIR/trading_stdout.log" \
                2>> "$LOG_DIR/trading_stderr.log" &
            trading_pid=$!
            echo "$trading_pid" > "$PID_FILE"
            last_start_time=$(date +%s)
            log "재시작 완료. 새 PID: $trading_pid"
        fi

        sleep 60  # 1분마다 체크
    done

    log "Night session 완료"
}

main "$@"
