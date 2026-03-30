"""셋업 API 엔드포인트 응답/요청 스키마를 정의한다.

Consumer Installer의 6개 셋업 엔드포인트에서 사용하는
Pydantic 모델을 관리한다. 서비스 설정 상태, API 키 저장,
연결 검증, 모델 다운로드 관련 스키마를 포함한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── 보조 모델 ──────────────────────────────────────────


class ServiceSetupStatus(BaseModel):
    """개별 서비스의 셋업 상태이다."""

    configured: bool = False
    validated: bool = False
    required: bool = True


class ModelSetupStatus(BaseModel):
    """전체 ML 모델 다운로드 현황이다."""

    all_downloaded: bool = False
    downloaded_count: int = 0
    total_count: int = 0


class ModelInfo(BaseModel):
    """개별 GGUF 모델 정보이다."""

    model_id: str
    name: str
    repo_id: str
    filename: str
    size_gb: float = 0.0
    downloaded: bool = False
    download_progress: float | None = None
    """다운로드 진행률이다. 0.0~1.0 범위이며, 다운로드 중이 아니면 None이다."""


# ── GET /api/setup/status ──────────────────────────────


class SetupStatusResponse(BaseModel):
    """셋업 완료 상태 종합 응답이다."""

    setup_complete: bool = False
    services: dict[str, ServiceSetupStatus] = Field(default_factory=dict)
    models: ModelSetupStatus = Field(default_factory=ModelSetupStatus)


# ── POST /api/setup/config ─────────────────────────────


class ConfigCurrentResponse(BaseModel):
    """현재 저장된 설정값을 마스킹하여 반환하는 응답이다."""

    keys: dict[str, str] = Field(default_factory=dict)
    """필드명 → 마스킹된 값 맵이다. 미설정 키는 빈 문자열이다."""


class SetupConfigRequest(BaseModel):
    """API 키 저장 요청이다. .env 파일을 생성하고 Vault를 리로드한다."""

    # KIS 실거래
    kis_app_key: str | None = None
    kis_app_secret: str | None = None
    kis_account_no: str | None = None
    kis_hts_id: str | None = None

    # KIS 모의투자
    kis_mock_app_key: str | None = None
    kis_mock_app_secret: str | None = None
    kis_mock_account_no: str | None = None

    # Claude AI
    claude_mode: str | None = None
    """인증 방식이다. 'oauth' 또는 'api_key' 중 하나이다."""
    claude_api_key: str | None = None

    # 텔레그램 (1차 수신자)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    # 텔레그램 (2~5차 수신자)
    telegram_bot_token_2: str | None = None
    telegram_chat_id_2: str | None = None
    telegram_bot_token_3: str | None = None
    telegram_chat_id_3: str | None = None
    telegram_bot_token_4: str | None = None
    telegram_chat_id_4: str | None = None
    telegram_bot_token_5: str | None = None
    telegram_chat_id_5: str | None = None

    # 외부 데이터
    fred_api_key: str | None = None
    finnhub_api_key: str | None = None

    # Reddit
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None

    # 매매 모드 (virtual 또는 real)
    trading_mode: str | None = None


class SetupConfigResponse(BaseModel):
    """API 키 저장 결과 응답이다."""

    success: bool = False
    message: str = ""
    env_path: str = ""


# ── POST /api/setup/validate/{service} ─────────────────


class SetupValidateRequest(BaseModel):
    """개별 서비스 API 키 연결 검증 요청이다."""

    service: str
    credentials: dict[str, str] = Field(default_factory=dict)


class SetupValidateResponse(BaseModel):
    """개별 서비스 연결 검증 결과 응답이다."""

    service: str
    valid: bool = False
    message: str = ""


# ── GET /api/setup/models ──────────────────────────────


class ModelsStatusResponse(BaseModel):
    """4개 GGUF 모델 존재/다운로드 현황 응답이다."""

    models: list[ModelInfo] = Field(default_factory=list)
    total_size_gb: float = 0.0
    downloaded_count: int = 0
    total_count: int = 0


# ── POST /api/setup/models/download & cancel ───────────


class ModelDownloadRequest(BaseModel):
    """모델 다운로드 시작 요청이다. model_ids가 None이면 전체 다운로드이다."""

    model_ids: list[str] | None = None


class ModelDownloadResponse(BaseModel):
    """모델 다운로드/취소 결과 응답이다."""

    status: str = ""
    message: str = ""


# ── LaunchAgent 관련 스키마 ──────────────────────────


class LaunchAgentInfo(BaseModel):
    """개별 LaunchAgent의 상태 정보이다."""

    label: str = ""
    installed: bool = False
    loaded: bool = False
    running: bool = False
    pid: int | None = None
    last_exit_code: int | None = None


class LaunchAgentStatusResponse(BaseModel):
    """LaunchAgent 전체 상태 응답이다."""

    server: LaunchAgentInfo = Field(default_factory=LaunchAgentInfo)
    autotrader: LaunchAgentInfo = Field(default_factory=LaunchAgentInfo)


class LaunchAgentInstallRequest(BaseModel):
    """LaunchAgent 설치 요청이다."""

    app_path: str = ""
    """번들 앱 경로이다. 빈 문자열이면 자동 감지를 시도한다."""


class LaunchAgentInstallResponse(BaseModel):
    """LaunchAgent 설치/제거 결과 응답이다."""

    success: bool = False
    message: str = ""
    server_installed: bool = False
    autotrader_installed: bool = False


# ── 업데이트 확인 관련 스키마 ─────────────────────────


class UpdateCheckResponse(BaseModel):
    """업데이트 확인 결과 응답이다."""

    update_available: bool = False
    current_version: str = ""
    latest_version: str = ""
    download_url: str = ""
    release_notes: str = ""


# ── 언인스톨 관련 스키마 ─────────────────────────────


class UninstallItem(BaseModel):
    """삭제 대상 항목 정보이다."""

    path: str = ""
    type: str = ""
    description: str = ""
    exists: bool = False
    size_bytes: int = 0
    deletable: bool = True


class UninstallPreviewResponse(BaseModel):
    """삭제 미리보기 응답이다."""

    items: list[UninstallItem] = Field(default_factory=list)
    total_size_bytes: int = 0
    existing_count: int = 0


class UninstallRequest(BaseModel):
    """삭제 실행 요청이다."""

    keep_data: bool = False
    """True이면 DB와 .env 파일을 보존한다."""


class UninstallResponse(BaseModel):
    """삭제 실행 결과 응답이다."""

    success: bool = False
    message: str = ""
    keep_data: bool = False
    deleted_count: int = 0


class DataFileInfo(BaseModel):
    """개별 데이터 파일 상태이다."""

    name: str = ""
    path: str = ""
    exists: bool = False
    size_bytes: int = 0
    description: str = ""


class DataStatusResponse(BaseModel):
    """기존 설치 데이터 감지 결과 응답이다."""

    has_previous_install: bool = False
    """이전 설치 흔적이 존재하는지 여부이다."""
    env_exists: bool = False
    db_exists: bool = False
    models_dir: str = ""
    data_dir: str = ""
    files: list[DataFileInfo] = Field(default_factory=list)
    models: list[ModelInfo] = Field(default_factory=list)


class TokenIssueResponse(BaseModel):
    """KIS 토큰 발급 결과 응답이다."""

    success: bool = False
    virtual_expires: str = ""
    real_expires: str = ""
    issued_at: str = ""
    error: str = ""
