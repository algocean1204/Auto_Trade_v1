"""LaunchAgent plist 파일을 생성/설치/제거한다.

macOS LaunchAgent를 프로그래밍 방식으로 관리하여
서버 자동 실행과 자동매매 스케줄링을 설정한다.
"""
from __future__ import annotations

import logging
import plistlib
import subprocess
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_app_support_dir, get_env_path

logger: logging.Logger = get_logger(__name__)

# LaunchAgent 식별자이다 (scripts/ 및 Flutter ServerLauncher와 동일해야 한다)
_SERVER_LABEL: str = "com.trading.server"
_AUTOTRADER_LABEL: str = "com.trading.autotrader"

# plist 설치 경로이다 (macOS 전용 기능이므로 ~/Library/ 고정이다)
_LAUNCH_AGENTS_DIR: Path = Path.home() / "Library" / "LaunchAgents"
_LOG_DIR: Path = Path.home() / "Library" / "Logs" / "trading"
# 참고: LaunchAgent는 macOS 전용 기능이다. Linux에서는 systemd 등을 사용해야 한다.


class LaunchAgentManager:
    """LaunchAgent plist 파일을 생성/설치/제거한다."""

    def __init__(self) -> None:
        """디렉토리 경로를 초기화한다."""
        self._agents_dir: Path = _LAUNCH_AGENTS_DIR
        self._log_dir: Path = _LOG_DIR

    # ── 내부 헬퍼 ────────────────────────────────────────

    def _server_plist_path(self) -> Path:
        """서버 LaunchAgent plist 경로를 반환한다."""
        return self._agents_dir / f"{_SERVER_LABEL}.plist"

    def _autotrader_plist_path(self) -> Path:
        """자동매매 LaunchAgent plist 경로를 반환한다."""
        return self._agents_dir / f"{_AUTOTRADER_LABEL}.plist"

    def _ensure_dirs(self) -> None:
        """필요한 디렉토리를 생성한다."""
        self._agents_dir.mkdir(parents=True, exist_ok=True)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _run_launchctl(self, *args: str) -> tuple[int, str, str]:
        """launchctl 명령을 실행하고 결과를 반환한다."""
        try:
            result = subprocess.run(
                ["launchctl", *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            logger.warning("launchctl %s 타임아웃", " ".join(args))
            return -1, "", "timeout"
        except FileNotFoundError:
            logger.error("launchctl 명령을 찾을 수 없다")
            return -1, "", "launchctl not found"

    def _unload_if_loaded(self, label: str, plist_path: Path) -> None:
        """이미 로드된 LaunchAgent를 언로드한다."""
        code, stdout, _ = self._run_launchctl("list", label)
        if code == 0:
            self._run_launchctl("unload", str(plist_path))
            logger.info("기존 LaunchAgent 언로드 완료: %s", label)

    def _build_server_plist(self, app_path: str) -> dict:
        """서버 LaunchAgent plist 딕셔너리를 생성한다.

        비정상 종료 시에만 자동 재시작한다 (KeepAlive.SuccessfulExit=false).
        정상 종료(워치독 08:00 셧다운 등)는 재시작하지 않는다.
        """
        working_dir = str(get_app_support_dir())
        log_path = str(self._log_dir / "server.log")

        return {
            "Label": _SERVER_LABEL,
            "ProgramArguments": [
                f"{app_path}/Contents/Resources/python_backend/trading_server",
            ],
            "WorkingDirectory": working_dir,
            "KeepAlive": {"SuccessfulExit": False},
            "RunAtLoad": True,
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
            "EnvironmentVariables": {
                "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
            },
        }

    def _build_autotrader_plist(self) -> dict:
        """자동매매 LaunchAgent plist 딕셔너리를 생성한다.

        23:00 KST에 매매를 시작하고 06:30 KST에 정지+EOD를 실행하는
        통합 디스패처 스크립트를 스케줄링한다.

        단일 LaunchAgent는 StartCalendarInterval 배열로 다중 스케줄을 등록할 수
        있지만 ProgramArguments는 하나만 지정 가능하다. 따라서 디스패처 스크립트가
        현재 시각을 판별하여 start/stop 중 적절한 동작을 실행한다.

        포트 파일에서 서버 포트를 동적으로 읽어 하드코딩을 방지한다.
        """
        from src.common.paths import get_data_dir

        # .env 절대 경로를 스크립트에 삽입하여 API_SECRET_KEY를 읽는다
        env_path = get_env_path()
        env_abs = str(env_path) if env_path else ""
        port_file = str(get_data_dir() / "server_port.txt")

        # 디스패처 스크립트: 현재 시각으로 start/stop을 자동 판별한다
        # 07시 이전(00~06시대)이면 stop, 그 외(22~23시대)이면 start를 실행한다
        dispatcher_script = (
            "#!/bin/bash\n"
            "# 자동매매 디스패처: 현재 시각에 따라 start 또는 stop을 실행한다\n"
            "HOUR=$(date +%H)\n"
            "\n"
            "# 서버 포트를 동적으로 탐색한다\n"
            f'PORT_FILE="{port_file}"\n'
            'if [ -f "$PORT_FILE" ]; then\n'
            '    PORT=$(cat "$PORT_FILE" 2>/dev/null | tr -d "[:space:]")\n'
            'fi\n'
            'PORT=${PORT:-9501}\n'
            "\n"
            "# .env에서 API_SECRET_KEY를 읽는다\n"
            f'API_KEY=$(grep "^API_SECRET_KEY=" "{env_abs}" 2>/dev/null '
            "| cut -d'=' -f2 | tr -d '\"' | tr -d \"'\")\n"
            "\n"
            'if [ "$HOUR" -lt 7 ]; then\n'
            "    # 06:30 트리거: 매매 정지 + EOD\n"
            "    # /api/trading/stop이 run_eod=true(기본값)로 EOD를 자동 실행한다\n"
            '    curl -s -X POST "http://localhost:$PORT/api/trading/stop" \\\n'
            '        -H "Authorization: Bearer $API_KEY" \\\n'
            '        -H "Content-Type: application/json" \\\n'
            '        >> "${HOME}/Library/Logs/trading/autotrader.log" 2>&1\n'
            "else\n"
            "    # 23:00 트리거: 자동매매 시작\n"
            '    curl -s -X POST "http://localhost:$PORT/api/trading/start" \\\n'
            '        -H "Authorization: Bearer $API_KEY" \\\n'
            '        -H "Content-Type: application/json" \\\n'
            '        >> "${HOME}/Library/Logs/trading/autotrader.log" 2>&1\n'
            "fi\n"
        )

        # 스크립트 파일을 생성한다
        scripts_dir = get_app_support_dir() / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        dispatcher_path = scripts_dir / "autotrader_dispatch.sh"
        dispatcher_path.write_text(dispatcher_script, encoding="utf-8")
        dispatcher_path.chmod(0o755)

        log_path = str(self._log_dir / "autotrader.log")

        # 23:00 매매 시작 + 06:30 매매 정지 두 개의 스케줄을 등록한다
        # 디스패처 스크립트가 현재 시각으로 적절한 동작을 자동 판별한다
        return {
            "Label": _AUTOTRADER_LABEL,
            "ProgramArguments": ["/bin/bash", str(dispatcher_path)],
            "StartCalendarInterval": [
                {"Hour": 23, "Minute": 0},   # 매매 시작
                {"Hour": 6, "Minute": 30},    # 매매 정지 + EOD
            ],
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
        }

    def _write_plist(self, path: Path, data: dict) -> None:
        """plist 파일을 바이너리 형식으로 기록한다."""
        with open(path, "wb") as f:
            plistlib.dump(data, f)
        logger.info("plist 파일 생성: %s", path)

    # ── 공개 API ─────────────────────────────────────────

    def install_server_agent(self, app_path: str) -> bool:
        """서버 LaunchAgent를 설치한다.

        Args:
            app_path: .app 번들 경로이다.

        Returns:
            설치 성공 여부이다.
        """
        try:
            self._ensure_dirs()
            plist_path = self._server_plist_path()

            # 기존 에이전트를 언로드한다
            self._unload_if_loaded(_SERVER_LABEL, plist_path)

            # plist를 생성하고 기록한다
            plist_data = self._build_server_plist(app_path)
            self._write_plist(plist_path, plist_data)

            # launchctl로 로드한다
            code, _, stderr = self._run_launchctl("load", str(plist_path))
            if code != 0:
                logger.error("서버 LaunchAgent 로드 실패: %s", stderr)
                return False

            logger.info("서버 LaunchAgent 설치 완료: %s", _SERVER_LABEL)
            return True
        except Exception:
            logger.exception("서버 LaunchAgent 설치 중 오류 발생")
            return False

    def install_autotrader_agent(self) -> bool:
        """자동매매 LaunchAgent를 설치한다.

        매일 23:00에 매매를 시작하는 스케줄을 등록한다.

        Returns:
            설치 성공 여부이다.
        """
        try:
            self._ensure_dirs()
            plist_path = self._autotrader_plist_path()

            # 기존 에이전트를 언로드한다
            self._unload_if_loaded(_AUTOTRADER_LABEL, plist_path)

            # plist를 생성하고 기록한다
            plist_data = self._build_autotrader_plist()
            self._write_plist(plist_path, plist_data)

            # launchctl로 로드한다
            code, _, stderr = self._run_launchctl("load", str(plist_path))
            if code != 0:
                logger.error("자동매매 LaunchAgent 로드 실패: %s", stderr)
                return False

            logger.info("자동매매 LaunchAgent 설치 완료: %s", _AUTOTRADER_LABEL)
            return True
        except Exception:
            logger.exception("자동매매 LaunchAgent 설치 중 오류 발생")
            return False

    def uninstall_all(self) -> bool:
        """모든 LaunchAgent를 해제하고 plist를 삭제한다.

        Returns:
            삭제 성공 여부이다.
        """
        try:
            success = True

            for label, plist_path in [
                (_SERVER_LABEL, self._server_plist_path()),
                (_AUTOTRADER_LABEL, self._autotrader_plist_path()),
            ]:
                # 로드된 에이전트를 언로드한다
                self._unload_if_loaded(label, plist_path)

                # plist 파일을 삭제한다
                if plist_path.exists():
                    plist_path.unlink()
                    logger.info("plist 삭제 완료: %s", plist_path)

            # 자동매매 스크립트를 정리한다
            scripts_dir = get_app_support_dir() / "scripts"
            if scripts_dir.exists():
                for script in scripts_dir.iterdir():
                    script.unlink()
                scripts_dir.rmdir()
                logger.info("자동매매 스크립트 디렉토리 정리 완료")

            logger.info("모든 LaunchAgent 삭제 완료")
            return success
        except Exception:
            logger.exception("LaunchAgent 삭제 중 오류 발생")
            return False

    def get_status(self) -> dict:
        """설치된 LaunchAgent 상태를 반환한다.

        Returns:
            서버와 자동매매 LaunchAgent의 설치/실행 상태 딕셔너리이다.
        """
        try:
            server_status = self._get_agent_status(_SERVER_LABEL)
            autotrader_status = self._get_agent_status(_AUTOTRADER_LABEL)

            return {
                "server": {
                    "label": _SERVER_LABEL,
                    "installed": self._server_plist_path().exists(),
                    "loaded": server_status["loaded"],
                    "running": server_status["running"],
                    "pid": server_status["pid"],
                    "last_exit_code": server_status["last_exit_code"],
                },
                "autotrader": {
                    "label": _AUTOTRADER_LABEL,
                    "installed": self._autotrader_plist_path().exists(),
                    "loaded": autotrader_status["loaded"],
                    "running": autotrader_status["running"],
                    "pid": autotrader_status["pid"],
                    "last_exit_code": autotrader_status["last_exit_code"],
                },
            }
        except Exception:
            logger.exception("LaunchAgent 상태 조회 중 오류 발생")
            return {
                "server": self._empty_agent_status(_SERVER_LABEL),
                "autotrader": self._empty_agent_status(_AUTOTRADER_LABEL),
            }

    def _get_agent_status(self, label: str) -> dict:
        """개별 LaunchAgent의 상태를 조회한다."""
        code, stdout, _ = self._run_launchctl("list", label)
        if code != 0:
            return {
                "loaded": False,
                "running": False,
                "pid": None,
                "last_exit_code": None,
            }

        # 출력 형식: "{PID}\t{lastExitCode}\t{label}"
        line = stdout.strip()
        parts = line.split("\t")
        pid_str = parts[0] if parts else "-"
        pid = int(pid_str) if pid_str != "-" and pid_str.isdigit() else None
        last_exit = (
            int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        )

        return {
            "loaded": True,
            "running": pid is not None,
            "pid": pid,
            "last_exit_code": last_exit,
        }

    def _empty_agent_status(self, label: str) -> dict:
        """빈 상태 딕셔너리를 반환한다."""
        return {
            "label": label,
            "installed": False,
            "loaded": False,
            "running": False,
            "pid": None,
            "last_exit_code": None,
        }

    def is_server_running(self) -> bool:
        """서버 LaunchAgent가 실행 중인지 확인한다.

        Returns:
            서버 프로세스가 실행 중이면 True이다.
        """
        try:
            status = self._get_agent_status(_SERVER_LABEL)
            return status["running"]
        except Exception:
            logger.exception("서버 실행 상태 확인 중 오류 발생")
            return False
