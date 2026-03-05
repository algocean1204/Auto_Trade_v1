"""
macOS LaunchAgent 설치/관리 스크립트.

com.trading.autotrader LaunchAgent를 설치하여 매일 22:50 KST에
트레이딩 시스템을 자동 시작한다. caffeinate를 통합하여 시스템 잠자기를 방지한다.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

# 프로젝트 루트 (scripts/ 상위)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PLIST_SRC = Path(__file__).resolve().parent / "com.trading.autotrader.plist"
_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
_PLIST_DST = _LAUNCH_AGENTS_DIR / "com.trading.autotrader.plist"
_LABEL = "com.trading.autotrader"
_LOG_DIR = Path.home() / "Library" / "Logs" / "trading"


def install() -> None:
    """LaunchAgent plist를 설치하고 launchctl로 등록한다."""
    # 로그 디렉토리 생성
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # LaunchAgents 디렉토리 확인
    _LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    # plist 파일 읽기 -> 경로 치환 -> 쓰기
    if not _PLIST_SRC.exists():
        print(f"[ERROR] plist 파일 없음: {_PLIST_SRC}")
        sys.exit(1)

    with open(_PLIST_SRC, "rb") as f:
        plist = plistlib.load(f)

    # 현재 환경의 Python 경로
    python_path = sys.executable
    main_script = str(_PROJECT_ROOT / "src" / "main.py")

    # ProgramArguments 경로 치환
    plist["ProgramArguments"] = [
        "/usr/bin/caffeinate",
        "-i",
        python_path,
        main_script,
    ]

    # 로그 경로 설정
    plist["StandardOutPath"] = str(_LOG_DIR / "trading_stdout.log")
    plist["StandardErrorPath"] = str(_LOG_DIR / "trading_stderr.log")

    # 워킹 디렉토리 설정
    plist["WorkingDirectory"] = str(_PROJECT_ROOT)

    # EnvironmentVariables에 PYTHONPATH 추가
    plist.setdefault("EnvironmentVariables", {})
    plist["EnvironmentVariables"]["PYTHONPATH"] = str(_PROJECT_ROOT)

    # 기존 plist가 있으면 먼저 unload
    if _PLIST_DST.exists():
        _run_launchctl("unload", str(_PLIST_DST), check=False)

    # plist 저장
    with open(_PLIST_DST, "wb") as f:
        plistlib.dump(plist, f)

    print(f"[OK] plist 설치 완료: {_PLIST_DST}")
    print(f"     Python: {python_path}")
    print(f"     Script: {main_script}")
    print(f"     Logs:   {_LOG_DIR}")

    # launchctl load
    _run_launchctl("load", str(_PLIST_DST))
    print(f"[OK] launchctl load 완료: {_LABEL}")


def uninstall() -> None:
    """LaunchAgent를 해제하고 plist 파일을 삭제한다."""
    if not _PLIST_DST.exists():
        print(f"[WARN] plist 파일 없음: {_PLIST_DST}")
        return

    _run_launchctl("unload", str(_PLIST_DST), check=False)
    _PLIST_DST.unlink()
    print(f"[OK] LaunchAgent 제거 완료: {_LABEL}")


def status() -> dict[str, str | bool]:
    """현재 LaunchAgent 상태를 확인한다.

    Returns:
        상태 딕셔너리 (installed, loaded, label, plist_path).
    """
    installed = _PLIST_DST.exists()

    loaded = False
    if installed:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
        )
        loaded = _LABEL in result.stdout

    return {
        "label": _LABEL,
        "installed": installed,
        "loaded": loaded,
        "plist_path": str(_PLIST_DST),
        "log_dir": str(_LOG_DIR),
    }


def get_logs(lines: int = 50) -> str:
    """최근 로그를 조회한다.

    Args:
        lines: 조회할 라인 수.

    Returns:
        로그 문자열. 파일이 없으면 안내 메시지를 반환한다.
    """
    stdout_log = _LOG_DIR / "trading_stdout.log"
    stderr_log = _LOG_DIR / "trading_stderr.log"

    output_parts: list[str] = []

    for log_path, label in [(stdout_log, "STDOUT"), (stderr_log, "STDERR")]:
        if log_path.exists():
            try:
                result = subprocess.run(
                    ["tail", f"-{lines}", str(log_path)],
                    capture_output=True,
                    text=True,
                )
                output_parts.append(f"=== {label} (last {lines} lines) ===")
                output_parts.append(result.stdout)
            except Exception as exc:
                output_parts.append(f"=== {label} ===")
                output_parts.append(f"[ERROR] 로그 읽기 실패: {exc}")
        else:
            output_parts.append(f"=== {label} ===")
            output_parts.append(f"로그 파일 없음: {log_path}")

    return "\n".join(output_parts)


def _run_launchctl(action: str, plist_path: str, check: bool = True) -> None:
    """launchctl 명령을 실행한다."""
    cmd = ["launchctl", action, plist_path]
    try:
        subprocess.run(cmd, check=check, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        if check:
            print(f"[ERROR] launchctl {action} 실패: {exc.stderr}")
            sys.exit(1)


def _print_usage() -> None:
    """사용법을 출력한다."""
    print("사용법: python scripts/launchagent_setup.py <command>")
    print()
    print("Commands:")
    print("  install    - LaunchAgent 설치 및 등록")
    print("  uninstall  - LaunchAgent 해제 및 삭제")
    print("  status     - 현재 상태 확인")
    print("  logs       - 최근 로그 조회 (기본 50줄)")
    print("  logs <N>   - 최근 N줄 로그 조회")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "install":
        install()
    elif command == "uninstall":
        uninstall()
    elif command == "status":
        info = status()
        print(f"Label:     {info['label']}")
        print(f"Installed: {info['installed']}")
        print(f"Loaded:    {info['loaded']}")
        print(f"Plist:     {info['plist_path']}")
        print(f"Log dir:   {info['log_dir']}")
    elif command == "logs":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        print(get_logs(lines=n))
    else:
        print(f"[ERROR] 알 수 없는 명령: {command}")
        _print_usage()
        sys.exit(1)
