"""F7.5 SetupEndpoints -- 소비자 설치 위저드 API이다.

첫 설치 시 API 키 입력, 서비스 연결 검증, 모델 다운로드,
LaunchAgent 관리, 업데이트 확인, 언인스톨 기능을 제공한다.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends, HTTPException, Path

from src.common.logger import get_logger
from src.common.paths import get_app_support_dir, is_bundled
from src.common.secret_vault import get_vault, reload_vault
from src.monitoring.endpoints._setup_validators import (
    SERVICE_KEYS,
    build_env_lines,
    dispatch_validate,
)
from src.monitoring.schemas.setup_schemas import (
    ConfigCurrentResponse,
    LaunchAgentInfo,
    LaunchAgentInstallRequest,
    LaunchAgentInstallResponse,
    LaunchAgentStatusResponse,
    ModelDownloadRequest,
    ModelDownloadResponse,
    ModelSetupStatus,
    ModelsStatusResponse,
    SetupConfigRequest,
    SetupConfigResponse,
    SetupStatusResponse,
    SetupValidateResponse,
    ServiceSetupStatus,
    TokenIssueResponse,
    UninstallItem,
    UninstallPreviewResponse,
    UninstallRequest,
    UninstallResponse,
    UpdateCheckResponse,
)
from src.monitoring.server.auth import verify_api_key
from src.common.broker_gateway import KIS_VIRTUAL_BASE, KIS_REAL_BASE

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

setup_router = APIRouter(prefix="/api/setup", tags=["setup"])

# 백그라운드 태스크 참조 — GC에 의한 조기 수거를 방지한다
_background_tasks: set[asyncio.Task] = set()


def _on_bg_task_done(task: asyncio.Task, label: str) -> None:
    """백그라운드 태스크 완료 콜백 — 참조를 제거하고 예외를 로깅한다."""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error("백그라운드 태스크 예외 (%s): %s", label, exc)


_system: InjectedSystem | None = None


def set_setup_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("SetupEndpoints 의존성 주입 완료")


async def _try_reinit_system(system: InjectedSystem) -> None:
    """broker/ai/telegram 컴포넌트를 현재 vault 키로 재초기화한다.

    NoOp 더미든 이미 실체 인스턴스든 무조건 싱글톤을 리셋하고 재생성한다.
    키 변경 후 재초기화 시에도 새 키가 반영되도록 보장한다.
    init 실패 시 구 싱글톤을 복원하여 기존 인스턴스라도 계속 사용 가능하게 한다.

    주의: reload_vault() 호출 후에 실행되므로 get_vault()로 새 vault를 가져와야 한다.
    """
    from src.orchestration.init.system_initializer import (
        _init_ai,
        _init_broker,
        _init_telegram,
    )

    from src.common.ai_gateway import reset_ai_client
    from src.common.broker_gateway import reset_broker_client
    from src.common.telegram_gateway import reset_telegram_sender

    c = system.components
    # reload_vault() 이후이므로 새 싱글톤을 가져와 시스템 전체에 반영한다
    vault = get_vault()
    c.vault = vault

    # BrokerClient 재초기화 — 구 싱글톤 백업 후 시도, 실패 시 복원한다
    old_broker = c.broker
    try:
        reset_broker_client()
        c.broker = _init_broker(vault)
        _logger.info("BrokerClient 재초기화 완료")
    except Exception as exc:
        # 싱글톤을 복원하여 구 인스턴스라도 계속 사용 가능하게 한다
        import src.common.broker_gateway as _bg
        _bg._instance = old_broker
        _logger.warning("BrokerClient 재초기화 실패 (구 인스턴스 유지): %s", exc)

    # AiClient 재초기화 — 동일 패턴이다
    old_ai = c.ai
    try:
        reset_ai_client()
        c.ai = _init_ai(vault)
        _logger.info("AiClient 재초기화 완료")
    except Exception as exc:
        import src.common.ai_gateway as _ag
        _ag._instance = old_ai
        _logger.warning("AiClient 재초기화 실패 (구 인스턴스 유지): %s", exc)

    # TelegramSender 재초기화 — 동일 패턴이다
    old_telegram = c.telegram
    try:
        reset_telegram_sender()
        c.telegram = _init_telegram(vault)
        _logger.info("TelegramSender 재초기화 완료")
    except Exception as exc:
        import src.common.telegram_gateway as _tg
        _tg._instance = old_telegram
        _logger.warning("TelegramSender 재초기화 실패 (구 인스턴스 유지): %s", exc)


# ── GET /api/setup/status ──────────────────────────────


@setup_router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status() -> SetupStatusResponse:
    """셋업 완료 상태를 종합하여 반환한다. 인증 불필요이다."""
    vault = get_vault()
    services: dict[str, ServiceSetupStatus] = {}
    for svc, keys in SERVICE_KEYS.items():
        configured = any(vault.has_secret(k) for k in keys)
        # 텔레그램은 선택 항목이다 — 위저드에서 건너뛸 수 있다
        required = svc == "kis"
        services[svc] = ServiceSetupStatus(configured=configured, required=required)

    # 모델 다운로드 상태를 확인한다 (model_manager가 없으면 기본값)
    models = ModelSetupStatus()
    try:
        from src.setup.model_manager import get_models_status
        st = get_models_status()
        models = ModelSetupStatus(
            all_downloaded=st["all_downloaded"],
            downloaded_count=st["downloaded_count"],
            total_count=st["total_count"],
        )
    except (ImportError, Exception) as exc:
        _logger.debug("모델 상태 조회 실패 (무시): %s", exc)

    required_ok = all(s.configured for s in services.values() if s.required)
    return SetupStatusResponse(
        setup_complete=required_ok and models.all_downloaded,
        services=services,
        models=models,
    )


# ── GET /api/setup/config/current ─────────────────────────


@setup_router.get("/config/current", response_model=ConfigCurrentResponse)
async def get_current_config(
    _key: str = Depends(verify_api_key),
) -> ConfigCurrentResponse:
    """현재 저장된 API 키를 마스킹하여 반환한다."""
    from src.monitoring.endpoints._setup_validators import ENV_KEY_MAP

    vault = get_vault()
    keys: dict[str, str] = {}
    for field_name, env_key in ENV_KEY_MAP.items():
        raw = vault.get_secret_or_none(env_key)
        if raw:
            keys[field_name] = vault.mask(env_key)
        else:
            keys[field_name] = ""

    # trading_mode도 포함한다
    trading_mode = vault.get_secret_or_none("TRADING_MODE")
    if trading_mode:
        keys["trading_mode"] = trading_mode

    return ConfigCurrentResponse(keys=keys)


# ── POST /api/setup/config ─────────────────────────────


@setup_router.post("/config", response_model=SetupConfigResponse)
async def save_config(
    body: SetupConfigRequest,
    _key: str = Depends(verify_api_key),
) -> SetupConfigResponse:
    """API 키를 .env 파일에 저장하고 vault를 리로드한다."""
    try:
        data = body.model_dump(exclude_none=True)

        # 기존 API_SECRET_KEY를 보존한다 — 재생성하면 실행 중인
        # auto_trading.sh 등이 구 키로 401 실패한다
        existing_vault = get_vault()
        existing_api_key = existing_vault.get_secret_or_none("API_SECRET_KEY")

        # 마스킹 값 필터링 — Flutter가 기존 키의 마스킹 값("abc4****")을
        # 그대로 재전송하면 실제 값이 마스킹 문자열로 덮어쓰여 서비스가 깨진다
        from src.monitoring.endpoints._setup_validators import ENV_KEY_MAP
        for field_name, env_key in ENV_KEY_MAP.items():
            val = data.get(field_name)
            if isinstance(val, str) and val == existing_vault.mask(env_key):
                del data[field_name]

        lines = build_env_lines(data)

        # build_env_lines가 새 키를 생성했으면 기존 키로 교체한다
        if existing_api_key:
            lines = [
                f"API_SECRET_KEY={existing_api_key}"
                if ln.startswith("API_SECRET_KEY=") else ln
                for ln in lines
            ]

        # .env 저장 경로를 결정한다 (번들이면 App Support, 아니면 프로젝트 루트)
        if is_bundled():
            env_path = get_app_support_dir() / ".env"
        else:
            from src.common.paths import get_project_root
            env_path = get_project_root() / ".env"

        # 기존 .env 키를 보존한다 — 위저드가 일부 키만 전송해도 나머지 키가 삭제되지 않는다
        if env_path.exists():
            new_keys = {ln.split("=", 1)[0] for ln in lines if "=" in ln}
            for eline in env_path.read_text(encoding="utf-8").splitlines():
                eline = eline.strip()
                if not eline or eline.startswith("#") or "=" not in eline:
                    continue
                ekey = eline.split("=", 1)[0]
                if ekey not in new_keys:
                    lines.append(eline)

        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        env_path.chmod(0o600)
        _logger.info(".env 파일 저장 완료: %s (%d개 키)", env_path, len(lines))

        # 위저드에서는 선택 항목(텔레그램 등)을 건너뛸 수 있으므로
        # setup_mode=True로 필수 키 검증을 생략한다
        reload_vault(setup_mode=True)
        _logger.info("vault 리로드 완료")

        # 필수 키가 설정되었으면 setup_mode를 해제하여 전체 API를 활성화한다
        vault = get_vault()
        has_kis = vault.has_secret("KIS_VIRTUAL_APP_KEY") or vault.has_secret(
            "KIS_REAL_APP_KEY",
        )
        if has_kis:
            from src.monitoring.server.api_server import set_setup_mode

            set_setup_mode(False)
            _logger.info("setup_mode 해제 — 정상 모드로 전환")

            # 시스템 재초기화를 시도한다 (setup_mode에서 스킵된 컴포넌트)
            if _system is not None:
                try:
                    await _try_reinit_system(_system)
                except Exception as exc:
                    _logger.warning("시스템 재초기화 부분 실패 (무시): %s", exc)

        return SetupConfigResponse(
            success=True,
            message=f"설정 저장 완료 ({len(lines)}개 키)",
            env_path=str(env_path),
        )
    except Exception as exc:
        _logger.exception(".env 저장 실패")
        raise HTTPException(status_code=500, detail=".env 저장 실패") from exc


# ── POST /api/setup/validate/{service} ─────────────────


@setup_router.post("/validate/{service}", response_model=SetupValidateResponse)
async def validate_service(
    service: str = Path(..., pattern=r"^[a-z_]+$"),
    creds: dict[str, str] | None = Body(default=None),
    _key: str = Depends(verify_api_key),
) -> SetupValidateResponse:
    """개별 서비스 API 키 연결을 검증한다."""
    if service not in SERVICE_KEYS:
        return SetupValidateResponse(
            service=service, valid=False,
            message=f"알 수 없는 서비스: {service}",
        )
    # 디버그: 수신된 자격증명 키 목록을 로깅한다 (값은 마스킹)
    masked = {k: f"{v[:4]}***" if v and len(v) > 4 else "***" for k, v in (creds or {}).items()}
    _logger.info("검증 요청: service=%s, creds_keys=%s", service, masked)
    try:
        valid, msg = await dispatch_validate(service, creds or {})
    except Exception as exc:
        _logger.exception("서비스 검증 중 예외 발생: %s", service)
        valid, msg = False, "검증 중 내부 오류가 발생했다"
    return SetupValidateResponse(service=service, valid=valid, message=msg)


# ── GET /api/setup/models ──────────────────────────────


@setup_router.get("/models", response_model=ModelsStatusResponse)
async def get_models_status() -> ModelsStatusResponse:
    """ML 모델 다운로드 현황을 반환한다. 인증 불필요이다."""
    try:
        from src.setup.model_manager import get_detailed_models_status
        return get_detailed_models_status()
    except ImportError:
        _logger.debug("model_manager 미구현 -- 빈 응답 반환")
        return ModelsStatusResponse()
    except Exception as exc:
        _logger.warning("모델 상태 조회 실패: %s", exc)
        return ModelsStatusResponse()


# ── POST /api/setup/models/download ────────────────────


@setup_router.post("/models/download", response_model=ModelDownloadResponse)
async def start_model_download(
    body: ModelDownloadRequest,
    _key: str = Depends(verify_api_key),
) -> ModelDownloadResponse:
    """모델 다운로드를 백그라운드 태스크로 시작한다."""
    try:
        from src.setup.model_manager import start_download
        task = asyncio.create_task(start_download(body.model_ids))
        _background_tasks.add(task)
        task.add_done_callback(lambda t: _on_bg_task_done(t, "model_download"))
        return ModelDownloadResponse(status="started", message="모델 다운로드를 시작했다")
    except ImportError:
        raise HTTPException(
            status_code=501, detail="model_manager가 아직 구현되지 않았다",
        ) from None
    except Exception as exc:
        _logger.exception("모델 다운로드 시작 실패")
        raise HTTPException(status_code=500, detail="모델 다운로드 시작 실패") from exc


# ── POST /api/setup/models/cancel ──────────────────────


@setup_router.post("/models/cancel", response_model=ModelDownloadResponse)
async def cancel_model_download(
    _key: str = Depends(verify_api_key),
) -> ModelDownloadResponse:
    """진행 중인 모델 다운로드를 취소한다."""
    try:
        from src.setup.model_manager import cancel_download
        await cancel_download()
        return ModelDownloadResponse(status="cancelled", message="모델 다운로드를 취소했다")
    except ImportError:
        raise HTTPException(
            status_code=501, detail="model_manager가 아직 구현되지 않았다",
        ) from None
    except Exception as exc:
        _logger.exception("모델 다운로드 취소 실패")
        raise HTTPException(status_code=500, detail="모델 다운로드 취소 실패") from exc


# ── POST /api/setup/launchagent/install ──────────────


@setup_router.post(
    "/launchagent/install",
    response_model=LaunchAgentInstallResponse,
)
async def install_launchagents(
    body: LaunchAgentInstallRequest | None = None,
    _key: str = Depends(verify_api_key),
) -> LaunchAgentInstallResponse:
    """서버 및 자동매매 LaunchAgent를 설치한다."""
    try:
        from src.setup.launchagent_manager import LaunchAgentManager

        manager = LaunchAgentManager()
        app_path = (body.app_path if body and body.app_path else "") or ""

        # app_path가 비어있으면 자동 감지를 시도한다
        if not app_path:
            import sys

            if getattr(sys, "frozen", False):
                # PyInstaller 번들에서 앱 경로를 추출한다
                import os

                exe_path = os.path.dirname(sys.executable)
                # MacOS/ -> Contents/ -> .app/
                app_path = os.path.dirname(os.path.dirname(exe_path))
            else:
                # 개발 모드에서는 프로젝트 루트를 사용한다
                from src.common.paths import get_project_root

                app_path = str(get_project_root())

        server_ok = manager.install_server_agent(app_path)
        autotrader_ok = manager.install_autotrader_agent()

        if server_ok and autotrader_ok:
            msg = "모든 LaunchAgent 설치 완료"
        elif server_ok:
            msg = "서버 LaunchAgent만 설치됨 (자동매매 실패)"
        elif autotrader_ok:
            msg = "자동매매 LaunchAgent만 설치됨 (서버 실패)"
        else:
            msg = "LaunchAgent 설치 실패"

        return LaunchAgentInstallResponse(
            success=server_ok or autotrader_ok,
            message=msg,
            server_installed=server_ok,
            autotrader_installed=autotrader_ok,
        )
    except Exception as exc:
        _logger.exception("LaunchAgent 설치 실패")
        raise HTTPException(status_code=500, detail="LaunchAgent 설치 실패") from exc


# ── POST /api/setup/launchagent/uninstall ────────────


@setup_router.post(
    "/launchagent/uninstall",
    response_model=LaunchAgentInstallResponse,
)
async def uninstall_launchagents(
    _key: str = Depends(verify_api_key),
) -> LaunchAgentInstallResponse:
    """모든 LaunchAgent를 해제하고 plist를 삭제한다."""
    try:
        from src.setup.launchagent_manager import LaunchAgentManager

        manager = LaunchAgentManager()
        success = manager.uninstall_all()

        return LaunchAgentInstallResponse(
            success=success,
            message="LaunchAgent 삭제 완료" if success else "LaunchAgent 삭제 실패",
            server_installed=False,
            autotrader_installed=False,
        )
    except Exception as exc:
        _logger.exception("LaunchAgent 삭제 실패")
        raise HTTPException(status_code=500, detail="LaunchAgent 삭제 실패") from exc


# ── GET /api/setup/launchagent/status ────────────────


@setup_router.get(
    "/launchagent/status",
    response_model=LaunchAgentStatusResponse,
)
async def get_launchagent_status() -> LaunchAgentStatusResponse:
    """LaunchAgent 설치/실행 상태를 반환한다. 인증 불필요이다."""
    try:
        from src.setup.launchagent_manager import LaunchAgentManager

        manager = LaunchAgentManager()
        status = manager.get_status()

        return LaunchAgentStatusResponse(
            server=LaunchAgentInfo(**status["server"]),
            autotrader=LaunchAgentInfo(**status["autotrader"]),
        )
    except Exception as exc:
        _logger.warning("LaunchAgent 상태 조회 실패: %s", exc)
        return LaunchAgentStatusResponse()


# ── GET /api/setup/update/check ──────────────────────


@setup_router.get(
    "/update/check",
    response_model=UpdateCheckResponse,
)
async def check_for_updates() -> UpdateCheckResponse:
    """새 버전이 있는지 확인한다. 인증 불필요이다."""
    try:
        from src.setup.update_checker import UpdateChecker

        checker = UpdateChecker()
        current = checker.get_current_version()
        result = await checker.check_for_updates(current)

        if result is None:
            return UpdateCheckResponse(
                update_available=False,
                current_version=current,
                latest_version=current,
            )

        return UpdateCheckResponse(
            update_available=True,
            current_version=current,
            latest_version=result["version"],
            download_url=result.get("url", ""),
            release_notes=result.get("notes", ""),
        )
    except Exception as exc:
        _logger.warning("업데이트 확인 실패: %s", exc)
        return UpdateCheckResponse()


# ── GET /api/setup/uninstall/preview ─────────────────


@setup_router.get(
    "/uninstall/preview",
    response_model=UninstallPreviewResponse,
)
async def preview_uninstall(
    _key: str = Depends(verify_api_key),
) -> UninstallPreviewResponse:
    """삭제될 항목 목록을 미리 표시한다."""
    try:
        from src.setup.uninstaller import Uninstaller

        uninstaller = Uninstaller()
        items = uninstaller.get_uninstall_items()

        item_models = [UninstallItem(**item) for item in items]
        existing_items = [i for i in item_models if i.exists]
        total_size = sum(i.size_bytes for i in existing_items)

        return UninstallPreviewResponse(
            items=item_models,
            total_size_bytes=total_size,
            existing_count=len(existing_items),
        )
    except Exception as exc:
        _logger.exception("삭제 미리보기 실패")
        return UninstallPreviewResponse()


# ── POST /api/setup/uninstall ────────────────────────


@setup_router.post(
    "/uninstall",
    response_model=UninstallResponse,
)
async def run_uninstall(
    body: UninstallRequest | None = None,
    _key: str = Depends(verify_api_key),
) -> UninstallResponse:
    """완전 삭제를 수행한다."""
    try:
        from src.setup.uninstaller import Uninstaller

        keep_data = body.keep_data if body else False
        uninstaller = Uninstaller()
        result = await uninstaller.uninstall(keep_data=keep_data)

        return UninstallResponse(
            success=result["success"],
            message=result["message"],
            keep_data=result["keep_data"],
            deleted_count=len(result.get("results", [])),
        )
    except Exception as exc:
        _logger.exception("삭제 실행 실패")
        raise HTTPException(status_code=500, detail="삭제 실행 실패") from exc


# ── POST /api/setup/token ─────────────────────────────


@setup_router.post("/token", response_model=TokenIssueResponse)
async def issue_token(
    _key: str = Depends(verify_api_key),
) -> TokenIssueResponse:
    """KIS 토큰을 발급하고 결과를 반환한다.

    Flutter 번들 모드에서 서버가 실행 중일 때 호출된다.
    vault에서 KIS 키를 읽어 가상/실전 토큰을 동시에 발급한다.
    인증 필수 — vault 시크릿을 사용하여 외부 KIS API에 토큰을 발급한다.
    """
    import aiohttp
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from src.common.paths import get_data_dir

    _kst = _tz(_td(hours=9))
    vault = get_vault()
    data_dir = get_data_dir()

    # 필수 키를 vault에서 가져온다
    required_keys = {
        "virtual": {
            "app_key": "KIS_VIRTUAL_APP_KEY",
            "app_secret": "KIS_VIRTUAL_APP_SECRET",
            "account": "KIS_VIRTUAL_ACCOUNT",
        },
        "real": {
            "app_key": "KIS_REAL_APP_KEY",
            "app_secret": "KIS_REAL_APP_SECRET",
            "account": "KIS_REAL_ACCOUNT",
        },
    }

    # 가상/실전 키를 개별적으로 수집한다. 한쪽만 있어도 해당 토큰만 발급한다.
    creds: dict[str, dict[str, str]] = {}
    for mode, keys in required_keys.items():
        mode_creds: dict[str, str] = {}
        for field, env_key in keys.items():
            val = vault.get_secret_or_none(env_key)
            if val:
                mode_creds[field] = val
        # 3개 필드가 모두 있어야 유효한 세트이다
        if len(mode_creds) == len(keys):
            creds[mode] = mode_creds

    if not creds:
        raise HTTPException(
            status_code=422,
            detail="KIS API 키가 하나도 설정되지 않았다 (가상 또는 실전 키 세트 필요)",
        )

    async def _issue_one(
        base_url: str, app_key: str, app_secret: str, account: str, is_real: bool,
    ) -> dict:
        """KIS OAuth2에서 토큰을 발급한다.

        일시적 서버 오류(503 등) 시 최대 2회 재시도한다.
        """
        import json as _json

        url = f"{base_url}/oauth2/tokenP"
        body = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
        last_error: Exception | None = None
        # 세션을 루프 바깥에서 1회만 생성하여 리소스 낭비를 방지한다
        async with aiohttp.ClientSession() as session:
            for attempt in range(3):
                async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        break
                    if resp.status in (500, 502, 503, 504) and attempt < 2:
                        # 일시적 서버 오류 — 2초 후 재시도한다
                        last_error = RuntimeError(f"HTTP {resp.status}: {data}")
                        await asyncio.sleep(2)
                        continue
                    raise RuntimeError(f"HTTP {resp.status}: {data}")
            else:
                raise last_error or RuntimeError("토큰 발급 재시도 실패")
        token = data.get("access_token")
        if not token:
            raise RuntimeError(
                f"KIS 응답에 access_token 필드 부재: {str(data)[:300]}"
            )
        expires_str = data.get("access_token_token_expired", "")
        token_data = {
            "account": account,
            "virtual": not is_real,
            "access_token": token,
            "token_expires_at": expires_str,
        }
        # 토큰 파일을 원자적으로 저장한다 (crash 시 깨진 JSON 방지)
        import tempfile as _tempfile
        import os as _os

        filename = "kis_real_token.json" if is_real else "kis_token.json"
        token_path = data_dir / filename
        token_path.parent.mkdir(parents=True, exist_ok=True)
        content = _json.dumps(token_data, ensure_ascii=False, indent=2, default=str)
        fd, tmp = _tempfile.mkstemp(
            dir=str(token_path.parent), suffix=".tmp", prefix=".token_",
        )
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            _os.chmod(tmp, 0o600)
            _os.replace(tmp, str(token_path))
        except BaseException:
            try:
                _os.unlink(tmp)
            except OSError:
                pass
            raise
        return token_data

    try:
        # 가상/실전 키가 있는 것만 발급한다
        tasks: list[asyncio.Task] = []
        task_labels: list[str] = []
        if "virtual" in creds:
            tasks.append(asyncio.ensure_future(_issue_one(
                KIS_VIRTUAL_BASE,
                creds["virtual"]["app_key"],
                creds["virtual"]["app_secret"],
                creds["virtual"]["account"],
                is_real=False,
            )))
            task_labels.append("virtual")
        if "real" in creds:
            tasks.append(asyncio.ensure_future(_issue_one(
                KIS_REAL_BASE,
                creds["real"]["app_key"],
                creds["real"]["app_secret"],
                creds["real"]["account"],
                is_real=True,
            )))
            task_labels.append("real")

        results = await asyncio.gather(*tasks, return_exceptions=True)
        result_map = dict(zip(task_labels, results))

        # 부분 성공 처리 — 한쪽만 실패해도 성공한 쪽의 토큰은 반환한다
        errors: list[str] = []
        virtual_data: dict | None = None
        real_data: dict | None = None
        for label, res in result_map.items():
            if isinstance(res, BaseException):
                errors.append(f"{label}: {res}")
                _logger.warning("토큰 발급 부분 실패 (%s): %s", label, res)
            elif label == "virtual":
                virtual_data = res
            else:
                real_data = res

        # 모두 실패하면 에러를 반환한다
        if virtual_data is None and real_data is None:
            _logger.error("토큰 발급 모두 실패: %s", errors)
            raise HTTPException(status_code=500, detail="토큰 발급 실패")

        now_kst = _dt.now(tz=_kst).strftime("%Y-%m-%d %H:%M:%S")
        return TokenIssueResponse(
            success=True,
            virtual_expires=virtual_data.get("token_expires_at", "") if virtual_data else "",
            real_expires=real_data.get("token_expires_at", "") if real_data else "",
            issued_at=now_kst,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception("토큰 발급 실패")
        raise HTTPException(status_code=500, detail="토큰 발급 실패") from exc
