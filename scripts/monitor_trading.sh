#!/bin/bash
# 트레이딩 시스템 모니터 - 오전 7시까지 5분마다 체크
# 스크립트 위치 기준으로 프로젝트 루트를 산출한다 (하드코딩 경로 제거)
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/monitor.log"
PORT_FILE="$PROJECT_DIR/data/server_port.txt"

# 로그 디렉토리를 확보한다
mkdir -p "$PROJECT_DIR/logs"

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
rotate_log "$LOG_FILE"

# 포트 파일에서 서버 포트를 읽는다. 없으면 9501을 반환한다.
read_port() {
    if [ -f "$PORT_FILE" ]; then
        local p
        p=$(cat "$PORT_FILE" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$p" ] && [ "$p" -ge 9501 ] 2>/dev/null && [ "$p" -le 9505 ] 2>/dev/null; then
            echo "$p"
            return
        fi
    fi
    echo "9501"
}

API_URL="http://localhost:$(read_port)"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_and_fix() {
    # 포트 파일을 다시 읽어 갱신한다 (서버 재시작 시 포트 변경 대응).
    API_URL="http://localhost:$(read_port)"

    # .env에서 인증 키를 읽는다
    local api_key=""
    if [ -f "$PROJECT_DIR/.env" ]; then
        api_key=$(grep -E '^API_SECRET_KEY=' "$PROJECT_DIR/.env" | cut -d'=' -f2- | tr -d '[:space:]')
    fi
    local auth_header=""
    if [ -n "$api_key" ]; then
        auth_header="Authorization: Bearer $api_key"
    fi

    # 1. 프로세스 생존 체크 (python3 또는 python으로 기동된 프로세스 모두 탐색)
    PROC=$(ps aux | grep -E "python3? -m src\.main" | grep -v grep | wc -l | tr -d ' ')
    if [ "$PROC" -eq "0" ]; then
        log "CRITICAL: 프로세스 죽음 감지. LaunchAgent(KeepAlive)가 자동 재시작할 때까지 대기한다."
        return
    fi

    # 2. API 서버 응답 체크
    STATUS=$(curl -s --max-time 10 -H "$auth_header" "$API_URL/api/trading/status" 2>/dev/null)
    if [ -z "$STATUS" ]; then
        log "WARN: API 서버 응답 없음. LaunchAgent(KeepAlive)가 복구할 때까지 대기한다."
        return
    fi

    # 3. 트레이딩 상태 파싱
    IS_TRADING=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_trading',False))" 2>/dev/null)
    IS_WINDOW=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_trading_window',False))" 2>/dev/null)
    SESSION=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_type','unknown'))" 2>/dev/null)

    if [ "$IS_TRADING" = "True" ]; then
        log "OK: trading=ON | window=$IS_WINDOW | session=$SESSION"
    else
        if [ "$IS_WINDOW" = "True" ]; then
            log "WARN: 트레이딩 꺼져있음! 자동매매 시작..."
            RESULT=$(curl -s -X POST --max-time 10 -H "$auth_header" "$API_URL/api/trading/start?force=true" 2>/dev/null)
            log "자동매매 시작 결과: $RESULT"
        else
            log "INFO: 거래시간 아님 | window=$IS_WINDOW | session=$SESSION"
        fi
    fi

    # 4. 최근 에러 체크
    ERRORS=$(tail -100 "$PROJECT_DIR/logs/trading_system.log" 2>/dev/null | grep -c "ERROR")
    if [ "$ERRORS" -gt "5" ]; then
        log "WARN: 최근 로그에 ERROR ${ERRORS}건"
        tail -100 "$PROJECT_DIR/logs/trading_system.log" | grep "ERROR" | tail -3 >> "$LOG_FILE"
    fi

    # 5. 뉴스 요약 체크
    NEWS=$(curl -s --max-time 10 -H "$auth_header" "$API_URL/api/news/summary" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'articles={d.get(\"total_articles\",0)}')" 2>/dev/null)
    if [ -n "$NEWS" ]; then
        log "NEWS: $NEWS"
    fi
}

log "=========================================="
log "모니터링 시작 (07:00 KST까지 5분 간격)"
log "=========================================="

while true; do
    HOUR=$(date '+%H')

    # 오전 7시~22시 사이면 종료
    if [ "$HOUR" -ge "7" ] && [ "$HOUR" -lt "23" ]; then
        log "=========================================="
        log "07:00 도달. 모니터링 종료"
        log "=========================================="
        break
    fi

    check_and_fix
    sleep 300
done
