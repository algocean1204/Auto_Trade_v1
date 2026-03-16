"""KIS 토큰 독립 발급 스크립트이다.

서버 시작 없이 KIS API 토큰만 발급한다. Flutter 앱에서 subprocess로 실행한다.
DB, Redis, FastAPI 서버 의존성이 전혀 없다.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_ENV_FILE = _PROJECT_ROOT / ".env"

_VIRTUAL_BASE = "https://openapivts.koreainvestment.com:29443"
_REAL_BASE = "https://openapi.koreainvestment.com:9443"
_KST = timezone(timedelta(hours=9))

# 토큰 파일 경로 상수
_VIRTUAL_TOKEN_PATH = _DATA_DIR / "kis_token.json"
_REAL_TOKEN_PATH = _DATA_DIR / "kis_real_token.json"


def _load_env() -> dict[str, str]:
    """.env 파일을 직접 파싱하여 환경변수 딕셔너리를 반환한다.

    빈 줄과 # 주석 줄은 건너뛴다.
    """
    env: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return env
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # 양쪽 따옴표 제거
        value = value.strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


def _load_cached_token(path: Path) -> dict | None:
    """캐싱된 토큰을 읽는다. 유효하지 않으면 None을 반환한다.

    broker_gateway.py의 _load_cached_token과 동일한 로직을 사용한다.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(data["token_expires_at"])
        # KIS API가 반환하는 만료시간은 KST이다. 타임존 없으면 KST로 처리한다.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=_KST)
        if datetime.now(tz=timezone.utc) < expires:
            return data
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def _save_token_cache(path: Path, data: dict) -> None:
    """토큰을 JSON 파일에 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


async def _issue_token(
    base_url: str,
    app_key: str,
    app_secret: str,
    account: str,
    is_real: bool,
) -> dict:
    """KIS OAuth2 엔드포인트에서 새 토큰을 발급받는다.

    성공 시 저장용 dict를 반환한다. 실패 시 예외를 발생시킨다.
    """
    url = f"{base_url}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {data}")

    expires_str: str = data.get("access_token_token_expired", "")
    return {
        "account": account,
        "virtual": not is_real,
        "access_token": data["access_token"],
        "token_expires_at": expires_str,
    }


def _parse_expires(token_data: dict | None) -> str:
    """토큰 데이터에서 만료시간 문자열을 반환한다. 없으면 빈 문자열을 반환한다."""
    if token_data is None:
        return ""
    return str(token_data.get("token_expires_at", ""))


async def _resolve_token(
    label: str,
    path: Path,
    base_url: str,
    app_key: str,
    app_secret: str,
    account: str,
    is_real: bool,
) -> tuple[dict, bool]:
    """캐시가 유효하면 재사용하고, 만료됐으면 새로 발급한다.

    반환값: (토큰 데이터 dict, 새로 발급했는지 여부)
    """
    cached = _load_cached_token(path)
    if cached is not None:
        # 유효한 캐시가 있으면 재발급 없이 반환한다
        return cached, False

    token_data = await _issue_token(base_url, app_key, app_secret, account, is_real)
    _save_token_cache(path, token_data)
    return token_data, True


async def main() -> None:
    """메인 실행 함수. 가상+실전 토큰을 동시에 처리하고 결과를 stdout에 출력한다."""
    env = _load_env()

    # 필수 환경변수 검증
    required = [
        "KIS_VIRTUAL_APP_KEY", "KIS_VIRTUAL_APP_SECRET", "KIS_VIRTUAL_ACCOUNT",
        "KIS_REAL_APP_KEY", "KIS_REAL_APP_SECRET", "KIS_REAL_ACCOUNT",
    ]
    missing = [k for k in required if not env.get(k)]
    if missing:
        result = {"success": False, "error": f"환경변수 누락: {', '.join(missing)}"}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    try:
        # 가상/실전 토큰 동시 처리 (asyncio.gather로 병렬 실행)
        virtual_task = _resolve_token(
            label="가상",
            path=_VIRTUAL_TOKEN_PATH,
            base_url=_VIRTUAL_BASE,
            app_key=env["KIS_VIRTUAL_APP_KEY"],
            app_secret=env["KIS_VIRTUAL_APP_SECRET"],
            account=env["KIS_VIRTUAL_ACCOUNT"],
            is_real=False,
        )
        real_task = _resolve_token(
            label="실전",
            path=_REAL_TOKEN_PATH,
            base_url=_REAL_BASE,
            app_key=env["KIS_REAL_APP_KEY"],
            app_secret=env["KIS_REAL_APP_SECRET"],
            account=env["KIS_REAL_ACCOUNT"],
            is_real=True,
        )

        (virtual_data, virtual_new), (real_data, real_new) = await asyncio.gather(
            virtual_task, real_task
        )

        now_kst = datetime.now(tz=_KST).strftime("%Y-%m-%d %H:%M:%S")
        result = {
            "success": True,
            "virtual_expires": _parse_expires(virtual_data),
            "virtual_reissued": virtual_new,
            "real_expires": _parse_expires(real_data),
            "real_reissued": real_new,
            "issued_at": now_kst,
        }
        print(json.dumps(result, ensure_ascii=False))

    except Exception as exc:
        result = {"success": False, "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
