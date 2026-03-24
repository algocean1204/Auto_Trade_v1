"""KIS 토큰 독립 발급 스크립트이다.

서버 시작 없이 KIS API 토큰만 발급한다. Flutter 앱에서 subprocess로 실행한다.
DB, Redis, FastAPI 서버 의존성이 전혀 없다.
외부 패키지 의존성 없이 stdlib만 사용하여 번들 모드에서 시스템 Python3으로 실행 가능하다.

번들 모드에서는 --env-file, --data-dir 인자로 경로를 지정할 수 있다.
미지정 시 프로젝트 루트 기준 기본 경로를 사용한다.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_path_args() -> tuple[Path, Path]:
    """CLI 인자에서 --env-file, --data-dir를 파싱한다.

    번들 모드에서는 .env와 data 디렉토리가 Application Support에 있으므로
    Flutter가 이 인자를 전달한다. 미지정 시 프로젝트 루트 기준 기본값을 사용한다.
    """
    env_file = _PROJECT_ROOT / ".env"
    data_dir = _PROJECT_ROOT / "data"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--env-file" and i + 1 < len(args):
            env_file = Path(args[i + 1])
            i += 2
        elif args[i] == "--data-dir" and i + 1 < len(args):
            data_dir = Path(args[i + 1])
            i += 2
        else:
            i += 1

    return env_file, data_dir


_ENV_FILE, _DATA_DIR = _parse_path_args()

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
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, OSError):
        pass
    return None


def _save_token_cache(path: Path, data: dict) -> None:
    """토큰을 JSON 파일에 원자적으로 저장한다.

    임시 파일에 먼저 기록한 뒤 rename으로 교체하여
    프로세스 crash 시 빈 파일/깨진 JSON을 방지한다.
    파일 권한은 0o600으로 설정하여 소유자만 읽기/쓰기할 수 있다.
    """
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)

    # 같은 디렉토리에 임시 파일을 만들어야 rename이 원자적이다
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".token_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, str(path))
    except BaseException:
        # 실패 시 임시 파일을 정리한다
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _issue_token(
    base_url: str,
    app_key: str,
    app_secret: str,
    account: str,
    is_real: bool,
) -> dict:
    """KIS OAuth2 엔드포인트에서 새 토큰을 발급받는다.

    성공 시 저장용 dict를 반환한다. 실패 시 예외를 발생시킨다.
    일시적 서버 오류(503 등) 시 최대 2회 재시도한다.
    stdlib urllib만 사용하여 시스템 Python3에서도 실행 가능하다.
    """
    url = f"{base_url}/oauth2/tokenP"
    body = json.dumps({
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }).encode("utf-8")
    ctx = ssl.create_default_context()

    last_error: Exception | None = None
    data: dict = {}
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                break
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                data = json.loads(e.read().decode("utf-8"))
            except Exception:
                data = {"error": str(e)}
            if status in (500, 502, 503, 504) and attempt < 2:
                last_error = RuntimeError(f"HTTP {status}: {data}")
                time.sleep(2)
                continue
            raise RuntimeError(f"HTTP {status}: {data}")
        except urllib.error.URLError as e:
            if attempt < 2:
                last_error = RuntimeError(f"연결 실패: {e.reason}")
                time.sleep(2)
                continue
            raise RuntimeError(f"연결 실패: {e.reason}")
    else:
        raise last_error or RuntimeError("토큰 발급 재시도 실패")

    token = data.get("access_token")
    if not token:
        raise RuntimeError(
            f"KIS 응답에 access_token 필드 부재: {str(data)[:300]}"
        )
    expires_str: str = data.get("access_token_token_expired", "")
    return {
        "account": account,
        "virtual": not is_real,
        "access_token": token,
        "token_expires_at": expires_str,
    }


def _parse_expires(token_data: dict | None) -> str:
    """토큰 데이터에서 만료시간 문자열을 반환한다. 없으면 빈 문자열을 반환한다."""
    if token_data is None:
        return ""
    return str(token_data.get("token_expires_at", ""))


def _resolve_token(
    label: str,
    path: Path,
    base_url: str,
    app_key: str,
    app_secret: str,
    account: str,
    is_real: bool,
    force: bool = False,
) -> tuple[dict, bool]:
    """캐시가 유효하면 재사용하고, 만료됐으면 새로 발급한다.

    force=True이면 캐시를 무시하고 강제 재발급한다.
    반환값: (토큰 데이터 dict, 새로 발급했는지 여부)
    """
    if not force:
        cached = _load_cached_token(path)
        if cached is not None:
            # 유효한 캐시가 있으면 재발급 없이 반환한다
            return cached, False

    token_data = _issue_token(base_url, app_key, app_secret, account, is_real)
    _save_token_cache(path, token_data)
    return token_data, True


def main() -> None:
    """메인 실행 함수. 가상+실전 토큰을 순차 처리하고 결과를 stdout에 출력한다.

    --force 옵션: 캐시를 무시하고 강제 재발급한다.
    stdlib만 사용하므로 asyncio 없이 순차 실행한다.
    """
    force = "--force" in sys.argv
    env = _load_env()

    # 가상/실전 키 세트를 개별 확인한다. 한쪽만 있어도 해당 토큰만 발급한다.
    virtual_keys = ["KIS_VIRTUAL_APP_KEY", "KIS_VIRTUAL_APP_SECRET", "KIS_VIRTUAL_ACCOUNT"]
    real_keys = ["KIS_REAL_APP_KEY", "KIS_REAL_APP_SECRET", "KIS_REAL_ACCOUNT"]
    has_virtual = all(env.get(k) for k in virtual_keys)
    has_real = all(env.get(k) for k in real_keys)

    if not has_virtual and not has_real:
        result = {"success": False, "error": "KIS API 키가 하나도 설정되지 않았다 (가상 또는 실전 키 세트 필요)"}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    try:
        virtual_data: dict | None = None
        virtual_new = False
        real_data: dict | None = None
        real_new = False

        if has_virtual:
            virtual_data, virtual_new = _resolve_token(
                label="가상",
                path=_VIRTUAL_TOKEN_PATH,
                base_url=_VIRTUAL_BASE,
                app_key=env["KIS_VIRTUAL_APP_KEY"],
                app_secret=env["KIS_VIRTUAL_APP_SECRET"],
                account=env["KIS_VIRTUAL_ACCOUNT"],
                is_real=False,
                force=force,
            )

        if has_real:
            real_data, real_new = _resolve_token(
                label="실전",
                path=_REAL_TOKEN_PATH,
                base_url=_REAL_BASE,
                app_key=env["KIS_REAL_APP_KEY"],
                app_secret=env["KIS_REAL_APP_SECRET"],
                account=env["KIS_REAL_ACCOUNT"],
                is_real=True,
                force=force,
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
    main()
