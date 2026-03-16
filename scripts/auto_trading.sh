#!/bin/bash
#
# AI Auto-Trading System V2 - Trading Schedule Script (API 기반)
#
# 23:00 KST에 LaunchAgent가 실행한다.
# 서버(com.trading.server)가 항상 실행 중인 상태에서 API로 매매를 제어한다.
#   - 23:00: POST /api/trading/start → 자동매매 시작
#   - 06:30: POST /api/trading/stop?run_eod=true → 자동매매 종료 + EOD 실행
# 서버 프로세스 관리는 start_server.sh가 담당하므로 여기서는 하지 않는다.
#

set -euo pipefail

# ============================================
# 설정
# ============================================
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/trading"
ENV_FILE="$PROJECT_ROOT/.env"
PORT_FILE="$PROJECT_ROOT/data/server_port.txt"
DEFAULT_PORT=9500
STOP_HOUR=6
STOP_MINUTE=30

# 포트 파일에서 현재 서버 포트를 읽는다. 파일이 없으면 기본값을 반환한다.
read_port() {
    if [ -f "$PORT_FILE" ]; then
        local port
        port=$(cat "$PORT_FILE" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$port" ] && [ "$port" -ge 9500 ] 2>/dev/null && [ "$port" -le 9505 ] 2>/dev/null; then
            echo "$port"
            return
        fi
    fi
    echo "$DEFAULT_PORT"
}

SERVER_URL="http://localhost:$(read_port)"

# API 키를 .env 파일에서 읽는다
API_KEY=""
if [ -f "$ENV_FILE" ]; then
    API_KEY=$(grep -E '^API_SECRET_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '[:space:]')
fi

if [ -z "$API_KEY" ]; then
    echo "ERROR: API_SECRET_KEY를 .env에서 찾을 수 없다" >&2
    exit 1
fi

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [TRADER] $1" | tee -a "$LOG_DIR/auto_trading.log"
}

# ============================================
# API 호출 헬퍼 (재시도 포함)
# ============================================
# HTTPBearer 인증 방식을 사용한다: Authorization: Bearer <token>
api_call() {
    local method="$1"
    local endpoint="$2"
    local max_retries="${3:-3}"
    local retry=0
    local response

    while [ $retry -lt $max_retries ]; do
        response=$(curl -s -w "\n%{http_code}" \
            -X "$method" \
            -H "Authorization: Bearer $API_KEY" \
            -H "Content-Type: application/json" \
            --max-time 30 \
            "${SERVER_URL}${endpoint}" 2>/dev/null) || true

        # 응답에서 HTTP 상태 코드와 본문을 분리한다
        local http_code
        http_code=$(echo "$response" | tail -1)
        local body
        body=$(echo "$response" | sed '$d')

        if [ -n "$http_code" ] && [ "$http_code" -ge 200 ] 2>/dev/null && [ "$http_code" -lt 300 ] 2>/dev/null; then
            echo "$body"
            return 0
        fi

        retry=$((retry + 1))
        log "API 호출 실패: $method $endpoint (HTTP: ${http_code:-timeout}, 재시도: $retry/$max_retries)"
        sleep 5
    done

    log "ERROR: API 호출 최종 실패: $method $endpoint"
    return 1
}

# ============================================
# 서버 헬스체크 (서버가 준비될 때까지 대기)
# ============================================
wait_for_server() {
    local max_retries=60  # 최대 5분 대기 (60 * 5초)
    local retry=0
    log "서버 상태 확인 중 (${SERVER_URL})..."

    while [ $retry -lt $max_retries ]; do
        # 포트 파일이 갱신될 수 있으므로 매번 다시 읽는다
        SERVER_URL="http://localhost:$(read_port)"

        # status 엔드포인트는 인증 불필요하다
        local response
        response=$(curl -s --max-time 5 "${SERVER_URL}/api/trading/status" 2>/dev/null) || true

        if [ -n "$response" ] && echo "$response" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
            log "서버 응답 확인 완료 (${SERVER_URL})"
            return 0
        fi

        retry=$((retry + 1))
        if [ $((retry % 6)) -eq 0 ]; then
            log "서버 대기 중... ($retry/$max_retries, 경과: $((retry * 5))초, URL: ${SERVER_URL})"
        fi
        sleep 5
    done

    log "ERROR: 서버 응답 없음. 서버(com.trading.server)가 실행 중인지 확인한다."
    return 1
}

# ============================================
# 종료 시간 확인
# ============================================
should_stop() {
    local current_hour=$(date '+%H' | sed 's/^0//')
    local current_minute=$(date '+%M' | sed 's/^0//')

    # 야간 세션: 23:00 ~ 06:30 (자정을 넘긴다)
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
# 매매 상태 확인
# ============================================
check_trading_status() {
    local response
    response=$(curl -s --max-time 10 "${SERVER_URL}/api/trading/status" 2>/dev/null) || true

    if [ -z "$response" ]; then
        echo "unknown"
        return 1
    fi

    # is_trading 필드를 추출한다
    local is_trading
    is_trading=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_trading', False))" 2>/dev/null) || true

    if [ "$is_trading" = "True" ]; then
        echo "running"
        return 0
    else
        echo "stopped"
        return 0
    fi
}

# ============================================
# 매매 시작 (API 호출)
# ============================================
start_trading() {
    log "자동매매 시작 요청 중..."

    local response
    response=$(api_call "POST" "/api/trading/start?force=true" 5) || {
        log "ERROR: 자동매매 시작 요청 실패"
        return 1
    }

    local status
    status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null) || true

    case "$status" in
        started)
            log "자동매매 시작 완료"
            ;;
        already_running)
            log "자동매매 이미 실행 중"
            ;;
        *)
            log "WARNING: 예상치 못한 응답: $status (원본: $response)"
            ;;
    esac

    return 0
}

# ============================================
# 매매 종료 (API 호출, EOD 포함)
# ============================================
stop_trading() {
    log "자동매매 종료 요청 중 (EOD 실행 포함)..."

    local response
    response=$(api_call "POST" "/api/trading/stop?run_eod=true" 5) || {
        log "ERROR: 자동매매 종료 요청 실패"
        return 1
    }

    local status
    status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null) || true

    case "$status" in
        stopped)
            log "자동매매 종료 완료 (EOD 실행됨)"
            ;;
        not_running)
            log "자동매매가 실행 중이 아니었다"
            ;;
        *)
            log "WARNING: 예상치 못한 응답: $status (원본: $response)"
            ;;
    esac

    return 0
}

# ============================================
# 클린업 (SIGTERM/SIGINT 수신 시)
# ============================================
cleanup() {
    log "트레이딩 스케줄러 종료 신호 수신"

    # 매매가 진행 중이면 EOD와 함께 종료한다
    local trading_status
    trading_status=$(check_trading_status)
    if [ "$trading_status" = "running" ]; then
        log "매매 진행 중 -- EOD와 함께 종료 요청한다"
        stop_trading || true
    fi

    log "트레이딩 스케줄러 종료 완료"
}

trap cleanup EXIT SIGTERM SIGINT

# ============================================
# 메인 실행
# ============================================
main() {
    log "=========================================="
    log "AI Auto-Trading System V2 - Night Session"
    log "=========================================="

    # 슬립 방지 (매매 세션 동안만 caffeinate 활성화)
    caffeinate -i -w $$ &
    log "caffeinate 활성화 (PID: $!, 부모 PID: $$)"

    # 이미 종료 시간이면 바로 종료한다
    if should_stop; then
        log "현재 시간이 종료 시간(${STOP_HOUR}:${STOP_MINUTE}) 이후이다. 종료한다."
        exit 0
    fi

    # 서버가 준비될 때까지 대기한다
    wait_for_server || {
        log "ERROR: 서버 미응답. 서버(com.trading.server) 상태를 확인한다."
        exit 1
    }

    # 자동매매 시작 (API 호출)
    start_trading || {
        log "ERROR: 자동매매 시작 실패. 종료한다."
        exit 1
    }

    # 워치독 루프: 종료 시간까지 매매 상태를 감시한다
    log "워치독 루프 시작 (종료 시간: ${STOP_HOUR}:$(printf '%02d' $STOP_MINUTE))"
    while true; do
        # 종료 시간 도달 확인
        if should_stop; then
            log "종료 시간(${STOP_HOUR}:$(printf '%02d' $STOP_MINUTE)) 도달. 매매를 종료한다."
            stop_trading || true
            break
        fi

        # 매매 상태 확인
        local trading_status
        trading_status=$(check_trading_status)

        case "$trading_status" in
            running)
                # 정상 -- 계속 감시한다
                ;;
            stopped)
                # 매매가 중단됨 (서버는 살아있지만 매매가 멈춤)
                log "WARNING: 매매가 중단되었다. 재시작을 시도한다."
                start_trading || log "WARNING: 매매 재시작 실패"
                ;;
            unknown)
                # 서버 응답 없음 -- 서버 복구를 기다린다
                log "WARNING: 서버 응답 없음. 서버 복구를 대기한다."
                ;;
        esac

        sleep 60  # 1분마다 체크한다
    done

    log "Night session 완료"
}

main "$@"
