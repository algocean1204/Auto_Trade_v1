#!/bin/bash
# 5분 주기 자동 모니터링 스크립트
# 서버 상태, 포지션, 에러를 확인하고 텔레그램으로 전송한다.

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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

API_URL="http://localhost:$(read_port)"
LOG_DIR="$PROJECT_ROOT/logs"
INTERVAL=300  # 5분

# 로그 디렉토리를 확보한다
mkdir -p "$LOG_DIR"

# .env에서 인증 키와 텔레그램 설정을 읽는다
ENV_FILE="$PROJECT_ROOT/.env"
_read_env() {
    grep "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2 | tr -d '"'"'"
}
API_KEY=$(_read_env "API_SECRET_KEY")
TG_TOKEN=$(_read_env "TELEGRAM_BOT_TOKEN")
TG_CHAT=$(_read_env "TELEGRAM_CHAT_ID")
AUTH="Authorization: Bearer $API_KEY"

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        -d "chat_id=${TG_CHAT}" \
        -d "text=$1" \
        -d "parse_mode=" > /dev/null 2>&1
}

check_and_restart() {
    # 프로세스 확인 (python3 또는 python으로 기동된 프로세스 모두 탐색)
    PID=$(pgrep -f "python3? -m src\.main" | head -1)
    if [ -z "$PID" ]; then
        send_telegram "🚨 [모니터링] 프로세스 죽음 감지! LaunchAgent(KeepAlive)가 자동 재시작할 때까지 대기한다."
        return 1
    fi

    # 포트 충돌 확인 (같은 포트에 2개 이상 바인딩)
    PORT_COUNT=$(pgrep -f "python3? -m src\.main" | wc -l | tr -d ' ')
    if [ "$PORT_COUNT" -gt 1 ]; then
        # 가장 최근 프로세스만 남기고 나머지 종료
        KEEP_PID=$(pgrep -f "python3? -m src\.main" | tail -1)
        for P in $(pgrep -f "python3? -m src\.main"); do
            if [ "$P" != "$KEEP_PID" ]; then
                kill "$P" 2>/dev/null
            fi
        done
        send_telegram "⚠️ [모니터링] 중복 프로세스 정리 (유지: PID $KEEP_PID)"
    fi

    # 포트 파일이 갱신될 수 있으므로 매번 다시 읽는다
    API_URL="http://localhost:$(read_port)"

    # API 서버 응답 확인
    STATUS=$(curl -s -m 10 -H "$AUTH" "${API_URL}/api/trading/status" 2>/dev/null)
    if [ -z "$STATUS" ]; then
        send_telegram "⚠️ [모니터링] API 서버 무응답 (${API_URL})"
        return 1
    fi

    IS_TRADING=$(echo "$STATUS" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('is_trading',False))" 2>/dev/null)
    SESSION=$(echo "$STATUS" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('session_type','?'))" 2>/dev/null)
    IS_WINDOW=$(echo "$STATUS" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('is_trading_window',False))" 2>/dev/null)

    # 매매 시간인데 매매가 안 돌고 있으면 시작
    if [ "$IS_WINDOW" = "True" ] && [ "$IS_TRADING" = "False" ]; then
        curl -s -X POST -H "$AUTH" "${API_URL}/api/trading/start?force=true" > /dev/null 2>&1
        send_telegram "🔄 [모니터링] 매매 시간인데 미실행 → 자동 시작 요청"
        sleep 5
        STATUS=$(curl -s -m 10 -H "$AUTH" "${API_URL}/api/trading/status" 2>/dev/null)
        IS_TRADING=$(echo "$STATUS" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('is_trading',False))" 2>/dev/null)
    fi

    # 포지션 조회
    POSITIONS=$(curl -s -m 10 -H "$AUTH" "${API_URL}/api/dashboard/positions?mode=virtual" 2>/dev/null)
    POS_COUNT=$(echo "$POSITIONS" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('count',0))" 2>/dev/null)
    POS_DETAIL=""
    if [ "$POS_COUNT" -gt 0 ]; then
        POS_DETAIL=$(echo "$POSITIONS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for p in d.get('positions',[]):
    print(f\"  {p['ticker']} {p['quantity']}주 {p.get('unrealized_pnl_pct',0):.2f}% (\${p.get('unrealized_pnl',0):.2f})\")
" 2>/dev/null)
    fi

    # 최근 에러 수 (로그 마지막 200줄 기준)
    RECENT_ERRORS=$(tail -200 "${LOG_DIR}/trading_system.log" 2>/dev/null | grep -c "ERROR" || echo "0")

    # 최근 체결
    LAST_TRADE=$(grep "진입:" "${LOG_DIR}/trading_system.log" | tail -1 | sed 's/.*진입: //' 2>/dev/null)
    if [ -z "$LAST_TRADE" ]; then
        LAST_TRADE="없음"
    fi

    # KIS API 타임아웃 수 (최근 로그)
    KIS_TIMEOUTS=$(tail -200 "${LOG_DIR}/trading_system.log" | grep -c "ConnectionTimeoutError\|일봉 조회 실패\|초당 거래건수" 2>/dev/null || echo "0")

    NOW=$(date '+%Y-%m-%d %H:%M KST')

    # 메시지 구성
    MSG="[5분 모니터링] ${NOW}
━━━━━━━━━━━━━━
서버: PID ${PID} | ${API_URL}
매매: ${IS_TRADING} (${SESSION})
━━━━━━━━━━━━━━"

    if [ "$POS_COUNT" -gt 0 ]; then
        MSG="${MSG}
포지션 ${POS_COUNT}개:
${POS_DETAIL}"
    else
        MSG="${MSG}
포지션: 없음"
    fi

    MSG="${MSG}
━━━━━━━━━━━━━━
최근 체결: ${LAST_TRADE}
KIS 타임아웃: ${KIS_TIMEOUTS}건 (최근)
총 에러: ${RECENT_ERRORS}건"

    send_telegram "$MSG"
}

is_trading_hours() {
    # KST 기준 20:00~07:30 범위만 모니터링한다 (미국 장 시간대 + 여유)
    HOUR=$(date '+%H' | sed 's/^0//')
    if [ "$HOUR" -ge 20 ] || [ "$HOUR" -lt 8 ]; then
        return 0
    fi
    return 1
}

echo "[monitor] 5분 주기 모니터링 시작 ($(date))"
while true; do
    if ! is_trading_hours; then
        send_telegram "📴 [모니터링] 장 마감 시간 -- 모니터링 자동 종료 ($(date '+%H:%M KST'))"
        echo "[monitor] 장 마감 시간 도달 -- 자동 종료 ($(date))"
        break
    fi
    check_and_restart
    sleep $INTERVAL
done
