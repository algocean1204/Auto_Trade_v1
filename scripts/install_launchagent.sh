#!/bin/bash
#
# LaunchAgent 설치/제거 스크립트이다.
#
# 서버(com.trading.server)와 자동매매(com.trading.autotrader) 두 LaunchAgent를
# 현재 사용자/프로젝트 경로에 맞게 생성하여 설치한다.
# scripts/ 내 plist 파일은 개발자 참조용이며, 이 스크립트가 실제 설치용 plist를 동적 생성한다.
#

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LA_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/trading"

# ── plist 동적 생성 함수 ──

generate_server_plist() {
    cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trading.server</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_ROOT}/scripts/start_server.sh</string>
    </array>

    <!-- 비정상 종료 시에만 자동 재시작한다. 정상 종료(08:00 워치독 등)는 재시작하지 않는다 -->
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <!-- load 시 자동 시작한다 -->
    <key>RunAtLoad</key>
    <true/>

    <!-- 홈 디렉토리로 설정 (Documents는 TCC 보호 대상) -->
    <key>WorkingDirectory</key>
    <string>${HOME}</string>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/server_launchagent_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/server_launchagent_stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>${PROJECT_ROOT}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:${HOME}/.local/bin</string>
    </dict>

    <!-- 비정상 종료 후 재시작까지 30초 대기 (빠른 재시작 루프 방지) -->
    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
PLIST
}

generate_autotrader_plist() {
    cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trading.autotrader</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_ROOT}/scripts/auto_trading.sh</string>
    </array>

    <!-- 홈 디렉토리로 설정 (Documents는 TCC 보호 대상) -->
    <key>WorkingDirectory</key>
    <string>${HOME}</string>

    <!-- 매일 23:00 KST 시작 -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>23</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/launchagent_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/launchagent_stderr.log</string>

    <!-- 비정상 종료 시 재시작 -->
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>${PROJECT_ROOT}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:${HOME}/.local/bin</string>
    </dict>
</dict>
</plist>
PLIST
}

# ── 설치/제거 명령 ──

install_all() {
    echo "LaunchAgent 설치 중..."
    echo "  프로젝트: $PROJECT_ROOT"
    echo "  사용자: $(whoami)"

    # 디렉토리 생성
    mkdir -p "$LA_DIR" "$LOG_DIR"

    # 스크립트 실행 권한 부여
    chmod +x "$SCRIPT_DIR/auto_trading.sh"
    chmod +x "$SCRIPT_DIR/start_server.sh"

    # 기존 등록 해제
    for label in com.trading.server com.trading.autotrader; do
        if launchctl list 2>/dev/null | grep -q "$label"; then
            launchctl unload "$LA_DIR/${label}.plist" 2>/dev/null || true
        fi
    done

    # plist 동적 생성 및 설치
    generate_server_plist > "$LA_DIR/com.trading.server.plist"
    generate_autotrader_plist > "$LA_DIR/com.trading.autotrader.plist"

    # 등록
    launchctl load "$LA_DIR/com.trading.server.plist"
    launchctl load "$LA_DIR/com.trading.autotrader.plist"

    echo ""
    echo "설치 완료!"
    echo "  - 서버: load 시 자동 시작, 비정상 종료 시 자동 재시작 (08:00 KST 자동 종료 안전장치)"
    echo "  - 자동매매: 매일 23:00 시작, 06:30 종료 (서버가 실행 중일 때만 동작)"
    echo "  - 로그: $LOG_DIR/"
    echo ""
    echo "상태 확인: $0 status"
}

uninstall_all() {
    echo "LaunchAgent 제거 중..."

    for label in com.trading.server com.trading.autotrader; do
        if launchctl list 2>/dev/null | grep -q "$label"; then
            launchctl unload "$LA_DIR/${label}.plist" 2>/dev/null || true
        fi
        rm -f "$LA_DIR/${label}.plist"
    done

    echo "LaunchAgent 제거 완료!"
}

show_status() {
    echo "LaunchAgent 상태:"
    launchctl list 2>/dev/null | grep trading || echo "  등록되지 않음"
    echo ""
    if [ -f "$LOG_DIR/server.pid" ]; then
        local pid
        pid=$(cat "$LOG_DIR/server.pid")
        if kill -0 "$pid" 2>/dev/null; then
            echo "서버 PID: $pid (실행 중)"
        else
            echo "서버 PID: $pid (종료됨)"
        fi
    else
        echo "서버: 실행 중이 아님"
    fi
}

case "${1:-install}" in
    install)  install_all ;;
    uninstall) uninstall_all ;;
    start)
        echo "수동 시작..."
        launchctl start com.trading.autotrader
        echo "시작됨. 로그: tail -f $LOG_DIR/auto_trading.log"
        ;;
    stop)
        echo "수동 종료..."
        launchctl stop com.trading.autotrader
        echo "종료됨."
        ;;
    status) show_status ;;
    *)
        echo "Usage: $0 {install|uninstall|start|stop|status}"
        exit 1
        ;;
esac
