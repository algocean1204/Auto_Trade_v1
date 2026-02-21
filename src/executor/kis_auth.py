"""
KIS OpenAPI 인증 모듈

한국투자증권 OpenAPI의 인증을 관리한다.
- App Key + App Secret -> Access Token 발급 (POST /oauth2/tokenP)
- 토큰 24시간 유효, 만료 1시간 전 자동 갱신
- 모의투자(virtual) / 실전투자 모드 전환
- hashkey 발급 (POST 요청 시 필요)
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_KIS_TOKEN_TIMEOUT: float = 10.0


class KISAuthError(Exception):
    """KIS 인증 관련 예외."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class KISAuth:
    """한국투자증권 OpenAPI 인증 관리자.

    Access Token 발급/갱신, 공통 헤더 생성, hashkey 발급을 담당한다.
    모의투자와 실전투자 모드를 지원하며, URL이 자동으로 전환된다.
    """

    REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
    VIRTUAL_BASE_URL = "https://openapivts.koreainvestment.com:29443"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account: str,
        virtual: bool = True,
    ) -> None:
        """KISAuth 인스턴스를 초기화한다.

        Args:
            app_key: KIS OpenAPI 앱 키.
            app_secret: KIS OpenAPI 앱 시크릿.
            account: 계좌번호 ("00000000-01" 형태).
            virtual: True이면 모의투자, False이면 실전투자.
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.account = account
        self.virtual = virtual
        self.base_url = self.VIRTUAL_BASE_URL if virtual else self.REAL_BASE_URL
        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None

        mode_label = "VIRTUAL" if virtual else "REAL"
        logger.info(
            "KISAuth initialized: mode=%s, account=%s***",
            mode_label,
            account[:4],
        )

    async def get_token(self) -> str:
        """Access Token을 발급하거나 캐시된 토큰을 반환한다.

        토큰이 만료 1시간 전이면 새로 발급한다.
        KIS API의 토큰 유효기간은 24시간이며, 안전 마진으로 23시간 후 갱신한다.

        Returns:
            유효한 Access Token 문자열.

        Raises:
            KISAuthError: 토큰 발급에 실패한 경우.
        """
        if self._is_token_valid():
            return self.access_token  # type: ignore[return-value]

        logger.info("Requesting new access token...")
        async with httpx.AsyncClient(timeout=_KIS_TOKEN_TIMEOUT) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/oauth2/tokenP",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": self.app_key,
                        "appsecret": self.app_secret,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Token request failed: HTTP %d - %s",
                    exc.response.status_code,
                    exc.response.text,
                )
                raise KISAuthError(
                    f"Token request failed: HTTP {exc.response.status_code}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                logger.error("Token request network error: %s", exc)
                raise KISAuthError(
                    f"Token request network error: {exc}"
                ) from exc

        data = resp.json()

        if "access_token" not in data:
            error_msg = data.get("error_description", str(data))
            logger.error("Token response missing access_token: %s", error_msg)
            raise KISAuthError(f"Invalid token response: {error_msg}")

        self.access_token = data["access_token"]
        # KIS 토큰 유효기간 24시간, 안전 마진 1시간
        self.token_expires_at = datetime.now() + timedelta(hours=23)

        logger.info(
            "Access token acquired, expires at %s",
            self.token_expires_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return self.access_token

    def _is_token_valid(self) -> bool:
        """현재 토큰이 아직 유효한지 확인한다."""
        if self.access_token is None or self.token_expires_at is None:
            return False
        return datetime.now() < self.token_expires_at - timedelta(hours=1)

    def get_headers(self, tr_id: str | None = None) -> dict[str, str]:
        """API 호출용 공통 헤더를 생성한다.

        Args:
            tr_id: 거래 ID. None이면 tr_id 헤더를 포함하지 않는다.

        Returns:
            인증 정보가 포함된 헤더 딕셔너리.

        Raises:
            KISAuthError: 토큰이 아직 발급되지 않은 경우.
        """
        if self.access_token is None:
            raise KISAuthError("Access token not initialized. Call get_token() first.")

        headers = {
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "Content-Type": "application/json; charset=utf-8",
        }
        if tr_id is not None:
            headers["tr_id"] = tr_id
        return headers

    async def get_hashkey(self, body: dict) -> str:
        """POST 요청에 필요한 hashkey를 발급한다.

        KIS API의 POST 주문 요청 시 body를 해싱한 hashkey가 필요하다.

        Args:
            body: 해시할 요청 바디 딕셔너리.

        Returns:
            hashkey 문자열.

        Raises:
            KISAuthError: hashkey 발급에 실패한 경우.
        """
        await self.get_token()

        async with httpx.AsyncClient(timeout=_KIS_TOKEN_TIMEOUT) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/uapi/hashkey",
                    headers={
                        "appkey": self.app_key,
                        "appsecret": self.app_secret,
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json=body,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Hashkey request failed: HTTP %d", exc.response.status_code
                )
                raise KISAuthError(
                    f"Hashkey request failed: HTTP {exc.response.status_code}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                logger.error("Hashkey request network error: %s", exc)
                raise KISAuthError(
                    f"Hashkey request network error: {exc}"
                ) from exc

        data = resp.json()
        hashkey = data.get("HASH")
        if hashkey is None:
            raise KISAuthError(f"Hashkey response missing HASH: {data}")

        return hashkey

    @property
    def account_number(self) -> str:
        """계좌번호 8자리를 반환한다."""
        return self.account.split("-")[0]

    @property
    def account_product_code(self) -> str:
        """계좌 상품코드 2자리를 반환한다."""
        return self.account.split("-")[1]

    @property
    def is_virtual(self) -> bool:
        """모의투자 모드 여부를 반환한다."""
        return self.virtual

    # ------------------------------------------------------------------
    # secret.json 저장/로드
    # ------------------------------------------------------------------

    def save_credentials(self, path: str | Path = "secret.json") -> None:
        """갱신된 Access Token을 JSON 파일로 저장한다.

        app_key, app_secret은 .env에서만 관리하므로 파일에 저장하지 않는다.
        Access Token(회전 가능한 값)만 저장하여 재시작 시 토큰 재발급을 방지한다.

        Args:
            path: 저장 경로. 기본값은 프로젝트 루트의 secret.json.
        """
        filepath = Path(path)
        # app_key / app_secret은 .env에서 읽어야 하므로 파일에 저장하지 않는다.
        data: dict = {
            "account": self.account,
            "virtual": self.virtual,
        }
        if self.access_token and self.token_expires_at:
            data["access_token"] = self.access_token
            data["token_expires_at"] = self.token_expires_at.isoformat()

        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Token saved to %s (app_key/secret excluded)", filepath)

    @classmethod
    def from_token_cache(
        cls,
        app_key: str,
        app_secret: str,
        account: str,
        virtual: bool,
        path: str | Path = "secret.json",
    ) -> "KISAuth":
        """JSON 파일에서 캐시된 토큰을 로드하여 인스턴스를 생성한다.

        app_key / app_secret은 .env에서 전달받아야 한다. 파일에서 읽지 않는다.
        저장된 Access Token이 아직 유효하면 토큰 재발급 없이 바로 API 호출이 가능하다.

        Args:
            app_key: KIS OpenAPI 앱 키 (.env에서 전달).
            app_secret: KIS OpenAPI 앱 시크릿 (.env에서 전달).
            account: 계좌번호.
            virtual: 모의투자 여부.
            path: 토큰 캐시 파일 경로.

        Returns:
            초기화된 KISAuth 인스턴스.

        Raises:
            FileNotFoundError: 파일이 존재하지 않는 경우.
            KISAuthError: JSON 파싱 실패.
        """
        filepath = Path(path)
        instance = cls(
            app_key=app_key,
            app_secret=app_secret,
            account=account,
            virtual=virtual,
        )

        if not filepath.exists():
            logger.info("Token cache not found at %s, will issue new token", filepath)
            return instance

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load token cache from %s: %s", filepath, exc)
            return instance

        # 저장된 토큰이 있으면 복원
        if "access_token" in data and "token_expires_at" in data:
            instance.access_token = data["access_token"]
            instance.token_expires_at = datetime.fromisoformat(data["token_expires_at"])
            if instance._is_token_valid():
                logger.info("Restored valid access token from %s", filepath)
            else:
                logger.info("Stored token expired, will re-issue on next API call")
                instance.access_token = None
                instance.token_expires_at = None

        return instance
