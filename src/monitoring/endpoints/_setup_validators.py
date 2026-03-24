"""셋업 API 서비스별 검증 + .env 빌드 로직이다.

setup.py에서 사용하는 서비스 연결 검증 함수와
.env 파일 내용 조립 함수를 분리하여 관리한다.
각 검증 함수는 실제 API 호출을 수행하여 연결 상태를 확인한다.
"""
from __future__ import annotations

import asyncio
import shutil

import aiohttp

from src.common.broker_gateway import KIS_VIRTUAL_BASE, KIS_REAL_BASE
from src.common.logger import get_logger
from src.indicators.misc.fred_fetcher import FRED_API_URL

_logger = get_logger(__name__)

# 필드명 → .env 키 매핑이다
ENV_KEY_MAP: dict[str, str] = {
    "kis_app_key": "KIS_REAL_APP_KEY",
    "kis_app_secret": "KIS_REAL_APP_SECRET",
    "kis_account_no": "KIS_REAL_ACCOUNT",
    "kis_hts_id": "KIS_HTS_ID",
    "kis_mock_app_key": "KIS_VIRTUAL_APP_KEY",
    "kis_mock_app_secret": "KIS_VIRTUAL_APP_SECRET",
    "kis_mock_account_no": "KIS_VIRTUAL_ACCOUNT",
    "claude_mode": "CLAUDE_MODE",
    "claude_api_key": "ANTHROPIC_API_KEY",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "telegram_bot_token_2": "TELEGRAM_BOT_TOKEN_2",
    "telegram_chat_id_2": "TELEGRAM_CHAT_ID_2",
    "telegram_bot_token_3": "TELEGRAM_BOT_TOKEN_3",
    "telegram_chat_id_3": "TELEGRAM_CHAT_ID_3",
    "telegram_bot_token_4": "TELEGRAM_BOT_TOKEN_4",
    "telegram_chat_id_4": "TELEGRAM_CHAT_ID_4",
    "telegram_bot_token_5": "TELEGRAM_BOT_TOKEN_5",
    "telegram_chat_id_5": "TELEGRAM_CHAT_ID_5",
    "fred_api_key": "FRED_API_KEY",
    "finnhub_api_key": "FINNHUB_API_KEY",
    "reddit_client_id": "REDDIT_CLIENT_ID",
    "reddit_client_secret": "REDDIT_CLIENT_SECRET",
}

# 서비스별 vault 키 그룹 -- 하나라도 있으면 configured=True이다
SERVICE_KEYS: dict[str, list[str]] = {
    "kis": ["KIS_REAL_APP_KEY", "KIS_VIRTUAL_APP_KEY"],
    "claude": ["ANTHROPIC_API_KEY", "CLAUDE_MODE"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "fred": ["FRED_API_KEY"],
    "finnhub": ["FINNHUB_API_KEY"],
    "reddit": ["REDDIT_CLIENT_ID"],
}

# KIS API 베이스 URL — broker_gateway에서 가져온다
_KIS_VIRTUAL_BASE = KIS_VIRTUAL_BASE
_KIS_REAL_BASE = KIS_REAL_BASE

# 검증용 HTTP 타임아웃(초)이다
_VALIDATE_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=10)


def _sanitize_env_value(value: object) -> str:
    """환경변수 값에서 개행 문자를 제거하여 .env 인젝션을 방지한다."""
    s = str(value)
    # 개행/캐리지리턴을 제거한다 — 이 문자가 포함되면 .env에 임의 라인을 주입할 수 있다
    return s.replace("\n", "").replace("\r", "")


def build_env_lines(data: dict[str, object]) -> list[str]:
    """요청 데이터에서 .env 파일 라인 목록을 조립한다."""
    lines: list[str] = []
    for field_name, env_key in ENV_KEY_MAP.items():
        value = data.get(field_name)
        if value is not None:
            lines.append(f"{env_key}={_sanitize_env_value(value)}")
    # trading_mode가 있으면 KIS_MODE + TRADING_MODE를 추가한다
    trading_mode = data.get("trading_mode")
    if trading_mode:
        safe_mode = _sanitize_env_value(trading_mode)
        lines.append(f"KIS_MODE={safe_mode}")
        lines.append(f"TRADING_MODE={safe_mode}")

    # 자동 생성 기본값 — 위저드 필드에 없지만 시스템이 필요로 하는 키이다
    import secrets as _secrets

    if not any(ln.startswith("API_SECRET_KEY=") for ln in lines):
        lines.append(f"API_SECRET_KEY={_secrets.token_urlsafe(32)}")
    if not any(ln.startswith("LOG_LEVEL=") for ln in lines):
        lines.append("LOG_LEVEL=INFO")
    if not any(ln.startswith("KIS_ACCOUNT=") for ln in lines):
        # 실전 계좌 → 모의 계좌 순서로 사용한다
        acct = data.get("kis_account_no") or data.get("kis_mock_account_no")
        if acct:
            lines.append(f"KIS_ACCOUNT={_sanitize_env_value(acct)}")
    if not any(ln.startswith("CLAUDE_MODE=") for ln in lines):
        lines.append("CLAUDE_MODE=local")
    return lines


async def dispatch_validate(
    service: str,
    creds: dict[str, str],
) -> tuple[bool, str]:
    """서비스 이름에 따라 적절한 검증 함수를 호출한다."""
    if service == "kis":
        return await validate_kis(creds)
    if service == "telegram":
        return await validate_telegram(creds)
    if service == "claude":
        return await validate_claude(creds)
    if service in ("fred", "finnhub", "reddit"):
        return await validate_simple(service, creds)
    return False, f"알 수 없는 서비스: {service}"


async def validate_kis(credentials: dict[str, str]) -> tuple[bool, str]:
    """KIS API 키로 토큰 발급 + 잔고 조회를 시도하여 검증한다.

    잔고가 0원이어도 연결 성공으로 처리한다.
    mock 필드가 'true'이면 모의투자 서버, 아니면 실전 서버를 사용한다.
    """
    app_key = credentials.get("app_key", "")
    app_secret = credentials.get("app_secret", "")
    if not app_key or not app_secret:
        return False, "app_key와 app_secret이 필요하다"

    is_mock = credentials.get("mock", "false") == "true"
    account_no = credentials.get("account_no", "")
    if not account_no:
        return False, "계좌번호(account_no)가 필요하다"

    base_url = _KIS_VIRTUAL_BASE if is_mock else _KIS_REAL_BASE
    mode_label = "모의투자" if is_mock else "실전투자"

    try:
        # 1단계: 토큰 발급을 시도한다
        token_url = f"{base_url}/oauth2/tokenP"
        token_body = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret,
        }
        async with aiohttp.ClientSession(timeout=_VALIDATE_TIMEOUT) as session:
            async with session.post(token_url, json=token_body) as resp:
                token_data = await resp.json()
                if resp.status != 200:
                    err_msg = token_data.get("msg1", str(token_data))
                    return False, f"{mode_label} 토큰 발급 실패: {err_msg}"

            access_token = token_data.get("access_token", "")
            if not access_token:
                return False, f"{mode_label} 토큰 발급 실패 (빈 토큰)"

            # 2단계: 잔고 조회를 시도한다 (해외주식 잔고)
            # 계좌번호에서 앞 8자리와 뒤 2자리를 분리한다
            account_parts = account_no.replace("-", "")
            if len(account_parts) < 10:
                # 계좌번호 형식이 맞지 않아도 토큰 발급은 성공했으므로 성공 처리한다
                return True, f"{mode_label} 토큰 발급 성공 (계좌번호 형식 확인 필요)"

            cano = account_parts[:8]
            acnt_prdt_cd = account_parts[8:10]

            # 해외주식 잔고조회 API이다
            balance_url = f"{base_url}/uapi/overseas-stock/v1/trading/inquire-balance"
            # 모의투자와 실전투자의 tr_id가 다르다
            tr_id = "VTTS3012R" if is_mock else "TTTC8434R"
            headers = {
                "authorization": f"Bearer {access_token}",
                "appkey": app_key,
                "appsecret": app_secret,
                "tr_id": tr_id,
                "Content-Type": "application/json; charset=utf-8",
            }
            params = {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt_prdt_cd,
                "OVRS_EXCG_CD": "NASD",
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            }
            async with session.get(
                balance_url, headers=headers, params=params,
            ) as resp:
                balance_data = await resp.json()
                rt_cd = balance_data.get("rt_cd", "")

                if rt_cd == "0":
                    # 성공 -- 잔고 정보를 추출한다
                    output2 = balance_data.get("output2", [])
                    if output2 and isinstance(output2, list):
                        tot_evlu_pfls_amt = output2[0].get(
                            "tot_evlu_pfls_amt", "0",
                        )
                        return True, (
                            f"{mode_label} 연결 성공 "
                            f"(총 평가금액: ${tot_evlu_pfls_amt})"
                        )
                    return True, f"{mode_label} 연결 성공 (잔고 조회 완료)"

                # 잔고 조회 실패지만 토큰은 성공했으므로 부분 성공 처리한다
                err_msg = balance_data.get("msg1", "알 수 없는 오류")
                _logger.warning(
                    "KIS %s 잔고 조회 실패 (토큰은 유효): %s", mode_label, err_msg,
                )
                return True, (
                    f"{mode_label} 토큰 발급 성공 (잔고 조회 미지원: {err_msg})"
                )

    except asyncio.TimeoutError:
        return False, f"{mode_label} 연결 시간 초과 (15초)"
    except aiohttp.ClientError as exc:
        _logger.warning("KIS %s 검증 네트워크 오류: %s", mode_label, exc)
        return False, f"{mode_label} 네트워크 오류: {exc}"
    except Exception as exc:
        _logger.warning("KIS %s 검증 실패: %s", mode_label, exc)
        return False, f"{mode_label} 연결 실패: {exc}"


async def validate_telegram(credentials: dict[str, str]) -> tuple[bool, str]:
    """텔레그램 봇 토큰으로 getMe + 테스트 메시지 전송을 검증한다.

    aiohttp로 직접 Telegram Bot API를 호출하여 의존성 문제를 회피한다.
    """
    token = credentials.get("bot_token", "")
    chat_id = credentials.get("chat_id", "")
    if not token:
        return False, "bot_token이 필요하다"
    if not chat_id:
        return False, "chat_id가 필요하다"

    base_url = f"https://api.telegram.org/bot{token}"

    try:
        async with aiohttp.ClientSession(timeout=_VALIDATE_TIMEOUT) as session:
            # 1단계: getMe로 봇 토큰 유효성을 확인한다
            async with session.get(f"{base_url}/getMe") as resp:
                me_data = await resp.json()
                if not me_data.get("ok"):
                    err_desc = me_data.get("description", "알 수 없는 오류")
                    return False, f"봇 토큰 검증 실패: {err_desc}"

            bot_name = me_data.get("result", {}).get("first_name", "Bot")

            # 2단계: 테스트 메시지를 전송한다
            msg_body = {
                "chat_id": chat_id,
                "text": f"[Stock Trader] 연결 테스트 성공 ({bot_name})",
            }
            async with session.post(
                f"{base_url}/sendMessage", json=msg_body,
            ) as resp:
                send_data = await resp.json()
                if send_data.get("ok"):
                    return True, f"텔레그램 연결 성공 ({bot_name})"

                err_desc = send_data.get("description", "알 수 없는 오류")
                # 봇은 유효하지만 chat_id가 잘못되었을 수 있다
                return False, f"메시지 전송 실패: {err_desc}"

    except asyncio.TimeoutError:
        return False, "텔레그램 연결 시간 초과 (15초)"
    except aiohttp.ClientError as exc:
        _logger.warning("텔레그램 검증 네트워크 오류: %s", exc)
        return False, f"텔레그램 네트워크 오류: {exc}"
    except Exception as exc:
        _logger.warning("텔레그램 검증 실패: %s", exc)
        return False, f"텔레그램 연결 실패: {exc}"


async def validate_claude(credentials: dict[str, str]) -> tuple[bool, str]:
    """Claude 연결을 검증한다.

    oauth 모드: claude CLI 존재 여부를 확인한다.
    api_key 모드: Anthropic Messages API에 최소 요청을 보내 키를 검증한다.
    """
    mode = credentials.get("mode", "api_key")

    if mode == "oauth":
        # Claude Code CLI 존재 여부를 확인한다
        claude_path = shutil.which("claude")
        if claude_path:
            return True, f"Claude Code 연결 확인 ({claude_path})"

        # 추가 경로를 확인한다
        import os
        additional_paths = [
            "/usr/local/bin/claude",
            os.path.expanduser("~/.claude/local/claude"),
            os.path.expanduser("~/.local/bin/claude"),
        ]
        for path in additional_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return True, f"Claude Code 연결 확인 ({path})"

        return False, "Claude CLI를 찾을 수 없다 (claude 명령어가 PATH에 없음)"

    # API Key 모드: 실제 Anthropic API 호출로 키를 검증한다
    api_key = credentials.get("api_key", "")
    if not api_key:
        return False, "API 키가 필요하다"

    if not api_key.startswith("sk-ant-"):
        return False, "API 키 형식이 올바르지 않다 (sk-ant- 접두사 필요)"

    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }
        async with aiohttp.ClientSession(timeout=_VALIDATE_TIMEOUT) as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
            ) as resp:
                if resp.status == 200:
                    return True, "API 키 연결 확인"
                if resp.status == 401:
                    return False, "API 키가 유효하지 않다 (인증 실패)"
                if resp.status == 403:
                    return False, "API 키 권한이 부족하다"
                if resp.status == 429:
                    # 요청 제한에 걸렸지만 키 자체는 유효하다
                    return True, "API 키 연결 확인 (요청 제한 중)"
                # 그 외 에러에서도 응답을 확인한다
                data = await resp.json()
                err_msg = data.get("error", {}).get("message", str(resp.status))
                return False, f"API 키 검증 실패: {err_msg}"

    except asyncio.TimeoutError:
        return False, "Anthropic API 연결 시간 초과 (15초)"
    except aiohttp.ClientError as exc:
        _logger.warning("Claude API 검증 네트워크 오류: %s", exc)
        return False, f"네트워크 오류: {exc}"
    except Exception as exc:
        _logger.warning("Claude API 검증 실패: %s", exc)
        return False, f"API 키 검증 실패: {exc}"


async def validate_simple(
    service: str, credentials: dict[str, str],
) -> tuple[bool, str]:
    """FRED, Finnhub, Reddit API 키를 실제 호출로 검증한다."""
    if service == "fred":
        return await _validate_fred(credentials)
    if service == "finnhub":
        return await _validate_finnhub(credentials)
    if service == "reddit":
        return await _validate_reddit(credentials)
    return False, f"알 수 없는 서비스: {service}"


async def _validate_fred(credentials: dict[str, str]) -> tuple[bool, str]:
    """FRED API 키로 VIXCLS 시리즈를 조회하여 검증한다."""
    api_key = credentials.get("api_key", "")
    if not api_key:
        return False, "FRED API 키가 필요하다"

    try:
        url = (
            f"{FRED_API_URL}"
            f"?series_id=VIXCLS&api_key={api_key}"
            "&file_type=json&sort_order=desc&limit=1"
        )
        async with aiohttp.ClientSession(timeout=_VALIDATE_TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    observations = data.get("observations", [])
                    if observations:
                        latest = observations[0].get("value", "N/A")
                        return True, f"FRED 연결 성공 (VIX: {latest})"
                    return True, "FRED 연결 성공"

                if resp.status in (400, 403):
                    return False, "FRED API 키가 유효하지 않다"

                return False, f"FRED API 오류 (HTTP {resp.status})"

    except asyncio.TimeoutError:
        return False, "FRED API 연결 시간 초과"
    except Exception as exc:
        _logger.warning("FRED 검증 실패: %s", exc)
        return False, f"FRED 연결 실패: {exc}"


async def _validate_finnhub(credentials: dict[str, str]) -> tuple[bool, str]:
    """Finnhub API 키로 AAPL 시세를 조회하여 검증한다."""
    api_key = credentials.get("api_key", "")
    if not api_key:
        return False, "Finnhub API 키가 필요하다"

    try:
        url = f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={api_key}"
        async with aiohttp.ClientSession(timeout=_VALIDATE_TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    current_price = data.get("c", 0)
                    if current_price and current_price > 0:
                        return True, f"Finnhub 연결 성공 (AAPL: ${current_price})"
                    return True, "Finnhub 연결 성공"

                if resp.status == 401:
                    return False, "Finnhub API 키가 유효하지 않다"
                if resp.status == 403:
                    return False, "Finnhub API 키 권한이 부족하다"

                return False, f"Finnhub API 오류 (HTTP {resp.status})"

    except asyncio.TimeoutError:
        return False, "Finnhub API 연결 시간 초과"
    except Exception as exc:
        _logger.warning("Finnhub 검증 실패: %s", exc)
        return False, f"Finnhub 연결 실패: {exc}"


async def _validate_reddit(credentials: dict[str, str]) -> tuple[bool, str]:
    """Reddit OAuth 토큰 발급을 시도하여 검증한다."""
    client_id = credentials.get("client_id", "")
    client_secret = credentials.get("client_secret", "")
    if not client_id or not client_secret:
        return False, "client_id와 client_secret이 필요하다"

    try:
        auth = aiohttp.BasicAuth(client_id, client_secret)
        headers = {"User-Agent": "StockTrader/1.0"}
        body = {"grant_type": "client_credentials"}

        async with aiohttp.ClientSession(timeout=_VALIDATE_TIMEOUT) as session:
            async with session.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                headers=headers,
                data=body,
            ) as resp:
                data = await resp.json()
                if resp.status == 200 and "access_token" in data:
                    return True, "Reddit 연결 성공"

                error = data.get("error", "")
                if error == "invalid_grant" or resp.status == 401:
                    return False, "Reddit 인증 실패 (키 확인 필요)"

                return False, f"Reddit API 오류: {error or resp.status}"

    except asyncio.TimeoutError:
        return False, "Reddit API 연결 시간 초과"
    except Exception as exc:
        _logger.warning("Reddit 검증 실패: %s", exc)
        return False, f"Reddit 연결 실패: {exc}"
