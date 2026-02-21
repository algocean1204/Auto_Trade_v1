"""
프로젝트 설정 관리
.env 파일에서 환경변수를 로드하여 타입-안전한 설정 객체 제공
"""
from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """애플리케이션 전체 설정을 관리하는 클래스."""

    # KIS OpenAPI -- 실전/모의 분리
    kis_real_app_key: str = ""
    kis_real_app_secret: str = ""
    kis_virtual_app_key: str = ""
    kis_virtual_app_secret: str = ""
    kis_mode: str = "virtual"  # "virtual" 또는 "real"
    kis_hts_id: str = ""
    kis_real_account: str = ""
    kis_virtual_account: str = ""
    kis_account: str = ""  # deprecated: kis_real_account/kis_virtual_account 사용

    @computed_field
    @property
    def kis_app_key(self) -> str:
        """KIS_MODE에 따라 실전/모의 앱 키를 반환한다."""
        if self.kis_mode == "virtual":
            return self.kis_virtual_app_key
        return self.kis_real_app_key

    @computed_field
    @property
    def kis_app_secret(self) -> str:
        """KIS_MODE에 따라 실전/모의 앱 시크릿을 반환한다."""
        if self.kis_mode == "virtual":
            return self.kis_virtual_app_secret
        return self.kis_real_app_secret

    @computed_field
    @property
    def kis_virtual(self) -> bool:
        """모의투자 모드 여부를 반환한다."""
        return self.kis_mode == "virtual"

    @computed_field
    @property
    def kis_active_account(self) -> str:
        """KIS_MODE에 따라 실전/모의 계좌번호를 반환한다.

        계좌번호가 설정되지 않았거나 기본 더미값인 경우 ValueError를 발생시킨다.

        Raises:
            ValueError: 계좌번호가 빈 문자열이거나 더미값("00000000-01")인 경우.
        """
        account = self.kis_virtual_account if self.kis_mode == "virtual" else self.kis_real_account
        _dummy_values = {"", "00000000-01"}
        if account in _dummy_values:
            raise ValueError(
                "KIS 계좌번호가 설정되지 않았습니다. "
                ".env 파일에 KIS_VIRTUAL_ACCOUNT 또는 KIS_REAL_ACCOUNT를 설정하세요."
            )
        return account

    # Claude AI 설정
    # 실행 모드: "local" (Claude Code MAX 플랜 CLI) / "api" (Anthropic API 키)
    claude_mode: str = "local"
    # API 모드일 때만 필요. local 모드에서는 불필요하다.
    anthropic_api_key: str = ""

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "trading"
    db_password: str  # 기본값 없음: .env에서 반드시 설정해야 한다
    db_name: str = "trading_system"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    # Crawler API Keys (optional -- sources skip gracefully if not set)
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    dart_api_key: str = ""
    stocktwits_access_token: str = ""
    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""
    fred_api_key: str = ""

    # Telegram (1st recipient)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Telegram (2nd recipient - optional)
    telegram_bot_token_2: str = ""
    telegram_chat_id_2: str = ""

    # Trading
    trading_mode: str = "paper"  # paper or live
    log_level: str = "INFO"

    # API Server
    api_port: int = 8000
    api_secret_key: str = ""  # Bearer 토큰 인증 키. 비어 있으면 인증 비활성화 (개발 환경용)

    # DB Query Logging (개발용)
    # true로 설정하면 모든 SQL 쿼리를 로그에 출력한다 (프로덕션에서는 false)
    db_echo: bool = False

    @property
    def database_url(self) -> str:
        """비동기 SQLAlchemy용 PostgreSQL URL (asyncpg 드라이버)."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def sync_database_url(self) -> str:
        """동기 SQLAlchemy용 PostgreSQL URL."""
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        """Redis 연결 URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"
        return f"redis://{self.redis_host}:{self.redis_port}"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


_settings: Settings | None = None


def get_settings() -> Settings:
    """Settings 싱글톤 인스턴스를 반환한다."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
