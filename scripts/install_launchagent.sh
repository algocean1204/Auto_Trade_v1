#!/bin/bash
#
# LaunchAgent 설치/제거 스크립트
# 매일 23:00 KST 자동매매 시작, 06:30 KST 자동 종료
#

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLIST_SRC="$SCRIPT_DIR/com.trading.autotrader.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.trading.autotrader.plist"
LOG_DIR="$HOME/Library/Logs/trading"

case "${1:-install}" in
    install)
        echo "LaunchAgent 설치 중..."

        # 로그 디렉토리 생성
        mkdir -p "$LOG_DIR"

        # auto_trading.sh 실행 권한 부여
        chmod +x "$SCRIPT_DIR/auto_trading.sh"

        # 기존 등록 해제
        if launchctl list | grep -q "com.trading.autotrader"; then
            launchctl unload "$PLIST_DST" 2>/dev/null
        fi

        # plist 복사 및 등록
        cp "$PLIST_SRC" "$PLIST_DST"
        launchctl load "$PLIST_DST"

        echo "LaunchAgent 설치 완료!"
        echo "  - 매일 23:00에 자동 시작"
        echo "  - 06:30에 자동 종료"
        echo "  - 로그: $LOG_DIR/"
        echo ""
        echo "상태 확인: launchctl list | grep trading"
        echo "수동 시작: launchctl start com.trading.autotrader"
        echo "수동 종료: launchctl stop com.trading.autotrader"
        ;;

    uninstall)
        echo "LaunchAgent 제거 중..."

        if launchctl list | grep -q "com.trading.autotrader"; then
            launchctl unload "$PLIST_DST" 2>/dev/null
        fi
        rm -f "$PLIST_DST"

        echo "LaunchAgent 제거 완료!"
        ;;

    start)
        echo "수동 시작..."
        launchctl start com.trading.autotrader
        echo "시작됨. 로그 확인: tail -f $LOG_DIR/auto_trading.log"
        ;;

    stop)
        echo "수동 종료..."
        launchctl stop com.trading.autotrader
        echo "종료됨."
        ;;

    status)
        echo "LaunchAgent 상태:"
        launchctl list | grep trading || echo "등록되지 않음"
        echo ""
        if [ -f "$LOG_DIR/trading.pid" ]; then
            PID=$(cat "$LOG_DIR/trading.pid")
            if kill -0 "$PID" 2>/dev/null; then
                echo "Trading PID: $PID (실행 중)"
            else
                echo "Trading PID: $PID (종료됨)"
            fi
        else
            echo "Trading: 실행 중이 아님"
        fi
        ;;

    *)
        echo "Usage: $0 {install|uninstall|start|stop|status}"
        exit 1
        ;;
esac
