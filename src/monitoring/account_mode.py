"""계정 모드 관리 모듈.

virtual/real 모드별 KIS 클라이언트와 포지션 모니터를 관리한다.
대시보드 및 API 엔드포인트에서 모드에 따라 올바른 클라이언트를 반환한다.

사용 흐름:
    1. main.py 에서 AccountModeManager 인스턴스를 생성한다.
    2. virtual/real 각 모드의 KISClient + PositionMonitor를 register()로 등록한다.
    3. set_dependencies()를 통해 API 서버에 주입한다.
    4. 대시보드 엔드포인트에서 get_kis_client(mode), get_position_monitor(mode)로 조회한다.
"""

from __future__ import annotations

from typing import Any

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AccountModeManager:
    """모드별 KIS 클라이언트와 포지션 모니터 레지스트리.

    "virtual"과 "real" 두 가지 모드를 지원한다.
    각 모드에 독립적인 KISClient와 PositionMonitor를 등록하여
    대시보드에서 모드별 잔고/포지션을 정확하게 조회할 수 있다.

    Attributes:
        _kis_clients: 모드별 KISClient 딕셔너리.
        _position_monitors: 모드별 PositionMonitor 딕셔너리.
        _default_mode: 기본 모드 (KIS_MODE 환경변수).
    """

    def __init__(self) -> None:
        """AccountModeManager를 초기화한다."""
        self._kis_clients: dict[str, Any] = {}
        self._position_monitors: dict[str, Any] = {}
        self._default_mode: str = get_settings().kis_mode
        logger.info(
            "AccountModeManager 초기화 완료 (default_mode=%s)", self._default_mode
        )

    def register(
        self,
        mode: str,
        kis_client: Any,
        position_monitor: Any,
    ) -> None:
        """모드별 KIS 클라이언트와 포지션 모니터를 등록한다.

        Args:
            mode: "virtual" 또는 "real".
            kis_client: 해당 모드의 KISClient 인스턴스.
            position_monitor: 해당 모드의 PositionMonitor 인스턴스.
        """
        self._kis_clients[mode] = kis_client
        if position_monitor is not None:
            self._position_monitors[mode] = position_monitor
        logger.info(
            "AccountModeManager 모드 등록: mode=%s, kis=%s, monitor=%s",
            mode,
            type(kis_client).__name__ if kis_client else "None",
            type(position_monitor).__name__ if position_monitor else "None",
        )

    def get_kis_client(self, mode: str | None = None) -> Any | None:
        """모드에 해당하는 KIS 클라이언트를 반환한다.

        Args:
            mode: "virtual" 또는 "real". None이면 기본 모드를 사용한다.

        Returns:
            KISClient 인스턴스. 등록되지 않은 모드이면 None.
        """
        if mode is None:
            mode = self._default_mode
        return self._kis_clients.get(mode)

    def get_position_monitor(self, mode: str | None = None) -> Any | None:
        """모드에 해당하는 포지션 모니터를 반환한다.

        Args:
            mode: "virtual" 또는 "real". None이면 기본 모드를 사용한다.

        Returns:
            PositionMonitor 인스턴스. 등록되지 않은 모드이면 None.
        """
        if mode is None:
            mode = self._default_mode
        return self._position_monitors.get(mode)

    @property
    def default_mode(self) -> str:
        """기본 계정 모드를 반환한다."""
        return self._default_mode

    @property
    def registered_modes(self) -> list[str]:
        """등록된 모드 목록을 반환한다."""
        return list(self._kis_clients.keys())

    async def close_all(self) -> None:
        """등록된 모든 KIS 클라이언트를 종료한다.

        main.py shutdown 시 호출되어야 한다.
        기본 거래용 클라이언트(virtual)는 main.py에서 별도 종료하므로
        여기서는 대시보드 전용(real) 클라이언트만 종료한다.
        """
        for mode, client in self._kis_clients.items():
            try:
                if hasattr(client, "close"):
                    await client.close()
                    logger.info("KIS 클라이언트 종료 완료 (mode=%s)", mode)
            except Exception as exc:
                logger.warning("KIS 클라이언트 종료 실패 (mode=%s): %s", mode, exc)
