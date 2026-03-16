#!/usr/bin/env python3
"""야간 자동매매 모니터링 스크립트이다.

5분 간격으로 서버/매매 상태를 점검하고 오류 발생 시 자동 복구한다.
토큰 사용량을 추적하고 텔레그램으로 주기적 리포트를 전송한다.
07:20 KST에 최종 요약 리포트를 전송하고 종료한다.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import quote

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = Path.home() / "Library" / "Logs" / "trading"
MONITOR_LOG = PROJECT_ROOT / "logs" / "monitor_overnight.log"
TOKEN_USAGE_FILE = DATA_DIR / "token_usage.json"

# 설정 로드
_env: dict[str, str] = {}
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            _env[k.strip()] = v.strip()

TELEGRAM_TOKEN = _env.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_TOKEN_2 = _env.get("TELEGRAM_BOT_TOKEN_2", "")
TELEGRAM_CHAT_ID_2 = _env.get("TELEGRAM_CHAT_ID_2", "")
API_KEY = _env.get("API_SECRET_KEY", "")

# 포트 파일 경로이다. 서버가 동적으로 선택한 포트를 기록한다.
_PORT_FILE = PROJECT_ROOT / "data" / "server_port.txt"
_DEFAULT_PORT = 9500


def _read_server_port() -> int:
    """포트 파일에서 현재 서버 포트를 읽는다. 파일이 없으면 기본값을 반환한다."""
    try:
        if _PORT_FILE.exists():
            port = int(_PORT_FILE.read_text().strip())
            if 9500 <= port <= 9505:
                return port
    except (ValueError, OSError):
        pass
    return _DEFAULT_PORT


SERVER_URL = f"http://localhost:{_read_server_port()}"

# 타임존
KST = timezone(timedelta(hours=9))

# 상태 추적
_check_count = 0
_error_count = 0
_restart_count = 0
_start_time = time.time()
_last_hourly_report = 0.0
_last_status: str = "unknown"
_errors_log: list[str] = []
_trade_events: list[str] = []


def log(msg: str) -> None:
    """로그 파일과 stdout에 기록한다."""
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [MONITOR] {msg}"
    print(line, flush=True)
    try:
        MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with MONITOR_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_telegram(message: str) -> bool:
    """텔레그램 메시지를 전송한다. 2계정 동시 발송."""
    success = False
    pairs = [
        (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID),
        (TELEGRAM_TOKEN_2, TELEGRAM_CHAT_ID_2),
    ]
    for token, chat_id in pairs:
        if not token or not chat_id:
            continue
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = json.dumps({
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }).encode("utf-8")
            req = Request(url, data=data, headers={"Content-Type": "application/json"})
            resp = urlopen(req, timeout=15)
            if resp.status == 200:
                success = True
        except Exception as e:
            log(f"텔레그램 전송 실패 ({chat_id}): {e}")
    return success


def api_get(endpoint: str, timeout: int = 10) -> dict | None:
    """서버 API GET 요청이다."""
    try:
        req = Request(
            f"{SERVER_URL}{endpoint}",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        resp = urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def api_post(endpoint: str, timeout: int = 30) -> dict | None:
    """서버 API POST 요청이다."""
    try:
        req = Request(
            f"{SERVER_URL}{endpoint}",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        resp = urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log(f"API POST 실패 ({endpoint}): {e}")
        return None


def check_server_health() -> bool:
    """서버 응답 가능 여부를 확인한다. 포트 파일을 다시 읽어 최신 포트를 반영한다."""
    global SERVER_URL
    SERVER_URL = f"http://localhost:{_read_server_port()}"
    result = api_get("/api/trading/status")
    return result is not None


def get_trading_status() -> dict | None:
    """매매 상태를 조회한다."""
    return api_get("/api/trading/status")


def start_trading() -> bool:
    """자동매매를 시작한다."""
    global _restart_count
    result = api_post("/api/trading/start?force=true")
    if result and result.get("status") in ("started", "already_running"):
        _restart_count += 1
        log(f"매매 시작/재시작 성공 (#{_restart_count}): {result.get('status')}")
        return True
    log(f"매매 시작 실패: {result}")
    return False


def get_token_usage() -> dict:
    """토큰 사용량 파일을 읽는다."""
    try:
        if TOKEN_USAGE_FILE.exists():
            data = json.loads(TOKEN_USAGE_FILE.read_text(encoding="utf-8"))
            return data
    except Exception:
        pass
    return {}


def get_recent_errors(minutes: int = 5) -> list[str]:
    """최근 N분 내 로그 에러를 추출한다."""
    errors: list[str] = []
    log_file = PROJECT_ROOT / "logs" / "trading_system.log"
    if not log_file.exists():
        # 날짜별 로그 확인
        today = datetime.now(KST).strftime("%Y-%m-%d")
        log_file = PROJECT_ROOT / "logs" / f"trading_system.log.{today}"
        if not log_file.exists():
            return errors

    try:
        # 마지막 500줄만 검사한다
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        cutoff = datetime.now(KST) - timedelta(minutes=minutes)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M")

        for line in lines[-500:]:
            if "[ERROR]" in line and line[:20] >= f"[{cutoff_str}":
                # 불필요한 스택트레이스 제외
                if "Traceback" not in line and "File " not in line:
                    errors.append(line.strip()[:200])
    except Exception:
        pass
    return errors[-10:]  # 최대 10개


def get_positions_info() -> str:
    """현재 포지션 정보를 조회한다."""
    result = api_get("/api/positions")
    if not result:
        return "조회 실패"
    positions = result.get("positions", [])
    if not positions:
        return "포지션 없음"
    lines = []
    for p in positions:
        ticker = p.get("ticker", "?")
        qty = p.get("quantity", 0)
        pnl = p.get("unrealized_pnl_pct", 0)
        lines.append(f"  {ticker}: {qty}주 ({pnl:+.2f}%)")
    return "\n".join(lines)


def _format_source_section(title: str, store: dict, is_api: bool) -> list[str]:
    """API 또는 SDK 섹션을 포맷한다."""
    if not store:
        return [f"<b>{title}</b>: 호출 없음"]

    # 비용표 (API만 적용)
    cost_table = {
        "claude-opus-4-6": {"input": 15.0, "output": 75.0},
        "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    }

    lines = [f"<b>{title}</b>"]
    total_calls = 0
    total_input = 0
    total_output = 0
    total_errors = 0
    total_cost = 0.0

    for model, info in store.items():
        calls = int(info.get("calls", 0))
        inp = int(info.get("input_tokens", 0))
        out = int(info.get("output_tokens", 0))
        errs = int(info.get("errors", 0))

        total_calls += calls
        total_input += inp
        total_output += out
        total_errors += errs

        short = model.replace("claude-", "").replace("-20251001", "")
        lines.append(f"  {short}: {calls}회, {inp+out:,} tok")
        if errs:
            lines.append(f"    (에러 {errs}회)")

        if is_api:
            ci = cost_table.get(model, {"input": 3.0, "output": 15.0})
            cost = (inp * ci["input"] + out * ci["output"]) / 1_000_000
            total_cost += cost
            lines.append(f"    비용: ${cost:.4f}")

    lines.append(f"  소계: {total_calls}회, {total_input+total_output:,} tok")
    if is_api:
        lines.append(f"  <b>과금 비용: ${total_cost:.4f}</b>")
    else:
        lines.append("  비용: 구독 포함 (추가 과금 없음)")
    return lines


def format_token_report(usage_data: dict) -> str:
    """토큰 사용량을 텔레그램 메시지로 포맷한다. API/SDK 분리 표시."""
    api_store = usage_data.get("api", {})
    sdk_store = usage_data.get("sdk", {})
    if not api_store and not sdk_store:
        return "토큰 사용량: 데이터 없음"

    lines = ["<b>📊 AI 토큰 사용량 (API vs SDK 분리)</b>\n"]

    # API 섹션 (과금)
    lines.extend(_format_source_section("💰 API 호출 (토큰당 과금)", api_store, is_api=True))
    lines.append("")

    # SDK 섹션 (구독)
    lines.extend(_format_source_section("🔑 SDK/OAuth 호출 (구독 포함)", sdk_store, is_api=False))
    lines.append("")

    # 합산
    api_calls = sum(int(v.get("calls", 0)) for v in api_store.values())
    sdk_calls = sum(int(v.get("calls", 0)) for v in sdk_store.values())
    api_tokens = sum(int(v.get("input_tokens", 0)) + int(v.get("output_tokens", 0)) for v in api_store.values())
    sdk_tokens = sum(int(v.get("input_tokens", 0)) + int(v.get("output_tokens", 0)) for v in sdk_store.values())

    lines.append("<b>── 종합 ──</b>")
    lines.append(f"API: {api_calls}회 / {api_tokens:,} tok")
    lines.append(f"SDK: {sdk_calls}회 / {sdk_tokens:,} tok")
    lines.append(f"합계: {api_calls+sdk_calls}회 / {api_tokens+sdk_tokens:,} tok")

    elapsed = (time.time() - _start_time) / 3600.0
    if elapsed > 0 and (api_calls + sdk_calls) > 0:
        lines.append(f"\n경과: {elapsed:.1f}시간")
        lines.append(f"시간당: API {api_calls/max(elapsed,0.01):.1f}회, SDK {sdk_calls/max(elapsed,0.01):.1f}회")

    return "\n".join(lines)


def do_health_check() -> str:
    """5분 주기 헬스체크를 수행한다. 상태 문자열을 반환한다."""
    global _check_count, _error_count, _last_status
    _check_count += 1

    # 1. 서버 상태
    if not check_server_health():
        _error_count += 1
        _last_status = "server_down"
        msg = f"⚠️ 서버 응답 없음 (체크 #{_check_count})"
        log(msg)
        _errors_log.append(msg)
        return "server_down"

    # 2. 매매 상태
    status = get_trading_status()
    if status is None:
        _last_status = "status_fail"
        return "status_fail"

    is_trading = status.get("is_trading", False)
    is_window = status.get("is_trading_window", False)

    now_kst = datetime.now(KST)

    # 매매 창인데 매매가 안 돌고 있으면 재시작
    if is_window and not is_trading:
        _error_count += 1
        msg = f"⚠️ 매매 중단 감지! 재시작 시도 (체크 #{_check_count})"
        log(msg)
        _errors_log.append(msg)

        if start_trading():
            send_telegram(f"🔄 <b>매매 자동 재시작 완료</b>\n시각: {now_kst.strftime('%H:%M:%S')}")
        else:
            send_telegram(f"🚨 <b>매매 재시작 실패!</b>\n시각: {now_kst.strftime('%H:%M:%S')}\n수동 확인 필요")
        _last_status = "restarted"
        return "restarted"

    # 3. 최근 에러 확인
    recent_errors = get_recent_errors(minutes=5)
    if recent_errors:
        for err in recent_errors:
            if err not in _errors_log[-20:]:
                _errors_log.append(err)
        # 심각한 에러만 알림
        critical = [e for e in recent_errors if "CRITICAL" in e or "비상" in e]
        if critical:
            _error_count += len(critical)
            send_telegram(
                f"🚨 <b>심각한 오류 감지</b>\n"
                f"시각: {now_kst.strftime('%H:%M:%S')}\n\n"
                + "\n".join(critical[:3])
            )

    _last_status = "trading" if is_trading else "idle"
    return _last_status


def send_hourly_report() -> None:
    """매시간 상태 리포트를 전송한다."""
    global _last_hourly_report
    now = time.time()
    if now - _last_hourly_report < 3500:  # ~58분
        return
    _last_hourly_report = now

    now_kst = datetime.now(KST)
    status = get_trading_status()
    is_trading = status.get("is_trading", False) if status else False
    elapsed_h = (now - _start_time) / 3600.0

    # 토큰 사용량
    usage = get_token_usage()
    token_report = format_token_report(usage)

    # 포지션
    positions = get_positions_info()

    msg = (
        f"📋 <b>매시간 모니터링 리포트</b>\n"
        f"시각: {now_kst.strftime('%Y-%m-%d %H:%M')}\n"
        f"경과: {elapsed_h:.1f}시간\n\n"
        f"<b>상태</b>: {'🟢 매매 진행 중' if is_trading else '🔴 매매 중단'}\n"
        f"체크 횟수: {_check_count}회\n"
        f"오류 횟수: {_error_count}회\n"
        f"재시작 횟수: {_restart_count}회\n\n"
        f"<b>📈 포지션</b>\n{positions}\n\n"
        f"{token_report}"
    )
    send_telegram(msg)
    log("매시간 리포트 전송 완료")


def send_final_report() -> None:
    """최종 종합 리포트를 전송한다."""
    now_kst = datetime.now(KST)
    elapsed_h = (time.time() - _start_time) / 3600.0

    # 토큰 사용량
    usage = get_token_usage()
    token_report = format_token_report(usage)

    # 포지션
    positions = get_positions_info()

    # 에러 요약
    error_summary = "없음"
    if _errors_log:
        unique_errors = list(dict.fromkeys(_errors_log[-20:]))
        error_summary = "\n".join(f"  • {e[:100]}" for e in unique_errors[:10])

    msg = (
        f"📊 <b>야간 자동매매 최종 리포트</b>\n"
        f"{'='*30}\n\n"
        f"⏰ 모니터링 기간\n"
        f"  시작: {datetime.fromtimestamp(_start_time, KST).strftime('%H:%M:%S')}\n"
        f"  종료: {now_kst.strftime('%H:%M:%S')}\n"
        f"  총 {elapsed_h:.1f}시간\n\n"
        f"📋 <b>실행 통계</b>\n"
        f"  헬스체크: {_check_count}회\n"
        f"  오류 감지: {_error_count}회\n"
        f"  매매 재시작: {_restart_count}회\n\n"
        f"📈 <b>최종 포지션</b>\n{positions}\n\n"
        f"{token_report}\n\n"
        f"⚠️ <b>에러 로그</b>\n{error_summary}\n\n"
        f"{'='*30}\n"
        f"✅ 야간 모니터링 정상 종료"
    )
    send_telegram(msg)
    log("최종 리포트 전송 완료")


# 종료 목표 시각을 계산한다 (다음 07:20 KST)
def _calc_stop_time() -> datetime:
    """다음 07:20 KST를 계산한다."""
    now = datetime.now(KST)
    stop = now.replace(hour=7, minute=20, second=0, microsecond=0)
    # 현재 07:20 이후면 내일 07:20으로 설정
    if now >= stop:
        stop += timedelta(days=1)
    return stop

_STOP_TIME = _calc_stop_time()


def should_stop() -> bool:
    """목표 종료 시각(다음 07:20 KST) 도달 시 종료한다."""
    return datetime.now(KST) >= _STOP_TIME


def main() -> None:
    """메인 모니터링 루프이다."""
    global _last_hourly_report

    log("=" * 50)
    log("야간 자동매매 모니터링 시작")
    log(f"종료 예정: {_STOP_TIME.strftime('%Y-%m-%d %H:%M KST')}")
    log("=" * 50)

    # 시작 알림
    now_kst = datetime.now(KST)
    send_telegram(
        f"🔍 <b>야간 모니터링 시작</b>\n"
        f"시각: {now_kst.strftime('%Y-%m-%d %H:%M')}\n"
        f"종료: {_STOP_TIME.strftime('%m/%d %H:%M')} KST\n"
        f"점검 주기: 5분"
    )

    _last_hourly_report = time.time()  # 첫 리포트는 1시간 후

    # SIGTERM/SIGINT 핸들러
    def handle_signal(signum: int, frame: object) -> None:
        log(f"신호 수신 (sig={signum}), 최종 리포트 전송 후 종료")
        send_final_report()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        while True:
            # 종료 시간 확인
            if should_stop():
                log(f"{_STOP_TIME.strftime('%H:%M')} KST 도달 -- 최종 리포트 전송 후 종료")
                send_final_report()
                break

            # 헬스체크
            status = do_health_check()
            now_kst = datetime.now(KST)
            log(f"체크 #{_check_count}: {status} ({now_kst.strftime('%H:%M:%S')})")

            # 매시간 리포트
            send_hourly_report()

            # 5분 대기
            time.sleep(300)

    except KeyboardInterrupt:
        log("키보드 인터럽트 -- 최종 리포트 전송")
        send_final_report()
    except Exception as e:
        log(f"모니터링 예외: {e}")
        send_telegram(f"🚨 <b>모니터링 스크립트 오류</b>\n{str(e)[:200]}")
        raise


if __name__ == "__main__":
    main()
