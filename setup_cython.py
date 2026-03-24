"""Cython 컴파일 설정 -- 민감 모듈 5개를 .so 바이너리로 컴파일한다.

API 키 관리, AI 백엔드, 주문 실행, 진입 전략 모듈의 소스 코드를 보호하기 위해
Cython으로 컴파일하여 .so 공유 라이브러리를 생성한다.
PyInstaller 빌드 후 .pyc를 .so로 교체하는 post_build 기능을 포함한다.

사용법:
    python setup_cython.py build_ext --inplace
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

# Cython 미설치 시 친절한 에러 메시지를 출력한다
try:
    from Cython.Build import cythonize
except ImportError:
    print(
        "[오류] Cython이 설치되어 있지 않다.\n"
        "  설치 방법: pip install cython\n"
        "  이후 다시 실행한다: python setup_cython.py build_ext --inplace",
        file=sys.stderr,
    )
    sys.exit(1)

from setuptools import Extension, setup

# 프로젝트 루트 경로이다
_PROJECT_ROOT = Path(__file__).resolve().parent

# Cython 컴파일 대상 민감 모듈 5개이다
# (모듈 import 경로, 소스 파일 상대 경로)
_SENSITIVE_MODULES: list[tuple[str, str]] = [
    # C0.1: API 키 관리 -- 모든 시크릿의 유일한 접근 경로이다
    ("src.common.secret_vault", "src/common/secret_vault.py"),
    # C0.5a: Claude AI SDK 통합 -- 로컬 CLI 기반 AI 호출이다
    ("src.common.ai_backends.sdk_backend", "src/common/ai_backends/sdk_backend.py"),
    # C0.5b: Claude AI API 통합 -- Anthropic API 기반 AI 호출이다
    ("src.common.ai_backends.api_backend", "src/common/ai_backends/api_backend.py"),
    # F5.3: 주문 실행 로직 -- 매수/매도, 스나이퍼 엑스큐션이다
    ("src.executor.order.order_manager", "src/executor/order/order_manager.py"),
    # F4: 진입 전략 -- 7개 게이트 순차 평가이다
    ("src.strategy.entry.entry_strategy", "src/strategy/entry/entry_strategy.py"),
]


def _build_extensions() -> list[Extension]:
    """5개 민감 모듈에 대한 Cython Extension 객체 목록을 생성한다.

    각 모듈의 소스 파일 존재 여부를 검증하고,
    macOS arm64 타겟에 맞는 컴파일러 옵션을 설정한다.
    """
    extensions: list[Extension] = []

    for module_name, source_path in _SENSITIVE_MODULES:
        full_path = _PROJECT_ROOT / source_path
        if not full_path.exists():
            print(f"[경고] 소스 파일을 찾을 수 없다: {full_path}", file=sys.stderr)
            continue

        ext = Extension(
            name=module_name,
            sources=[str(source_path)],
            # Python 3 전용 컴파일이다
            define_macros=[("CYTHON_LIMITED_API", None)],
        )
        extensions.append(ext)

    if not extensions:
        print("[오류] 컴파일할 소스 파일이 하나도 없다.", file=sys.stderr)
        sys.exit(1)

    return extensions


def _get_cythonize_options() -> dict:
    """Cython 컴파일 옵션을 반환한다.

    Python 3 모드를 강제하고, 어노테이션 HTML을 생성하지 않는다.
    """
    return {
        "compiler_directives": {
            "language_level": "3",       # Python 3 문법을 강제한다
            "boundscheck": False,        # 배열 경계 검사를 비활성화한다 (성능 향상)
            "wraparound": False,         # 음수 인덱스 래핑을 비활성화한다
            "annotation_typing": True,   # 타입 어노테이션을 Cython 타입으로 활용한다
        },
        "annotate": False,  # HTML 어노테이션 파일을 생성하지 않는다
    }


def post_build(pyinstaller_dist_dir: str) -> bool:
    """PyInstaller 빌드 결과물에서 .pyc 파일을 컴파일된 .so 파일로 교체한다.

    PyInstaller가 생성한 dist 디렉토리 내의 .pyc 파일을 찾아
    동일 모듈 경로의 .so 파일로 교체한다.

    Args:
        pyinstaller_dist_dir: PyInstaller dist 디렉토리 경로이다.

    Returns:
        모든 교체가 성공하면 True, 하나라도 실패하면 False를 반환한다.
    """
    dist_path = Path(pyinstaller_dist_dir)
    if not dist_path.exists():
        print(f"[오류] dist 디렉토리가 존재하지 않는다: {dist_path}", file=sys.stderr)
        return False

    # macOS arm64 .so 파일 확장자 패턴이다
    # 예: secret_vault.cpython-312-darwin.so
    py_version = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    machine = platform.machine()  # arm64
    so_suffix = f".{py_version}-darwin.so"

    success_count = 0
    fail_count = 0

    for module_name, source_path in _SENSITIVE_MODULES:
        # 모듈 경로에서 .so 파일명을 결정한다
        module_parts = module_name.split(".")
        base_name = module_parts[-1]
        # 패키지 디렉토리 경로이다
        package_dir = "/".join(module_parts[:-1])

        # inplace 빌드에서 생성된 .so 파일 위치이다
        so_filename = f"{base_name}{so_suffix}"
        so_source = _PROJECT_ROOT / package_dir.replace(".", "/") / so_filename

        # .so 파일이 없으면 glob 패턴으로 검색한다 (버전 차이 대응)
        if not so_source.exists():
            so_dir = _PROJECT_ROOT / package_dir.replace(".", "/")
            candidates = list(so_dir.glob(f"{base_name}*.so"))
            if candidates:
                so_source = candidates[0]
            else:
                print(f"[실패] .so 파일을 찾을 수 없다: {module_name}", file=sys.stderr)
                fail_count += 1
                continue

        # dist 디렉토리 내 .pyc 파일 위치를 탐색한다
        # PyInstaller 번들 내에서 모듈 경로를 유지한다
        # 가능한 위치: dist/_internal/ 또는 dist/ 직접
        pyc_candidates: list[Path] = []

        # PyInstaller --onedir 모드: dist/app_name/_internal/ 아래에 .pyc가 위치한다
        for internal_dir in dist_path.rglob("_internal"):
            pyc_path = internal_dir / package_dir.replace(".", "/") / f"{base_name}.pyc"
            if pyc_path.exists():
                pyc_candidates.append(pyc_path)

        # dist 디렉토리에서 직접 검색한다 (패키지 구조 유지 모드)
        for pyc_path in dist_path.rglob(f"{base_name}.pyc"):
            if pyc_path not in pyc_candidates:
                # 모듈 경로가 일치하는지 확인한다
                rel = pyc_path.relative_to(dist_path)
                rel_parts = list(rel.parts[:-1])  # 파일명 제외
                # _internal 이후 경로와 모듈 패키지 경로를 비교한다
                expected_parts = package_dir.split("/")
                if rel_parts[-len(expected_parts):] == expected_parts:
                    pyc_candidates.append(pyc_path)

        if not pyc_candidates:
            print(f"[건너뜀] .pyc 파일을 찾을 수 없다 (정상일 수 있음): {module_name}")
            continue

        # .pyc를 .so로 교체한다
        for pyc_path in pyc_candidates:
            target_so = pyc_path.with_suffix(".so")
            try:
                shutil.copy2(str(so_source), str(target_so))
                # 원본 .pyc를 제거한다
                pyc_path.unlink()
                print(f"[성공] 교체 완료: {pyc_path} -> {target_so}")
                success_count += 1
            except OSError as exc:
                print(f"[실패] 교체 오류: {pyc_path} -> {exc}", file=sys.stderr)
                fail_count += 1

    # 교체 결과를 요약한다
    print(f"\n--- post_build 결과 ---")
    print(f"성공: {success_count}건, 실패: {fail_count}건")

    if fail_count > 0:
        print("[경고] 일부 모듈 교체에 실패했다. 해당 모듈은 .pyc로 유지된다.")
        return False

    return True


def verify_so_files() -> bool:
    """inplace 빌드 후 .so 파일이 정상 생성되었는지 검증한다.

    각 모듈에 대해 .so 파일 존재 여부와 파일 크기를 확인한다.

    Returns:
        모든 .so 파일이 존재하면 True, 하나라도 없으면 False를 반환한다.
    """
    all_ok = True

    print("\n--- .so 파일 검증 ---")
    for module_name, source_path in _SENSITIVE_MODULES:
        module_parts = module_name.split(".")
        base_name = module_parts[-1]
        package_dir = "/".join(module_parts[:-1])
        so_dir = _PROJECT_ROOT / package_dir.replace(".", "/")

        # glob 패턴으로 .so 파일을 검색한다
        candidates = list(so_dir.glob(f"{base_name}*.so"))

        if candidates:
            so_file = candidates[0]
            size_kb = so_file.stat().st_size / 1024
            print(f"  [OK] {module_name} -> {so_file.name} ({size_kb:.1f} KB)")
        else:
            print(f"  [NG] {module_name} -> .so 파일을 찾을 수 없다")
            all_ok = False

    return all_ok


def _clean_build_artifacts() -> None:
    """빌드 과정에서 생성된 .c 중간 파일을 정리한다.

    Cython이 생성한 .c 파일은 .so 생성 후 불필요하므로 제거한다.
    원본 .py 파일은 절대 삭제하지 않는다.
    """
    print("\n--- 빌드 아티팩트 정리 ---")
    for module_name, source_path in _SENSITIVE_MODULES:
        c_path = _PROJECT_ROOT / source_path.replace(".py", ".c")
        if c_path.exists():
            c_path.unlink()
            print(f"  제거: {c_path.name}")


if __name__ == "__main__":
    # build_ext --inplace 명령 실행 시 Cython 컴파일을 수행한다
    extensions = _build_extensions()
    cython_options = _get_cythonize_options()

    print(f"=== Cython 컴파일 시작 ===")
    print(f"대상 모듈: {len(extensions)}개")
    print(f"플랫폼: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version}")
    print()

    setup(
        name="stock_trading_cython",
        # src 레이아웃 자동 감지를 방지한다 (inplace 복사 경로 오류 방지)
        package_dir={"": "."},
        ext_modules=cythonize(extensions, **cython_options),
        zip_safe=False,
        # setuptools에 script_args를 전달하여 명령줄 인자를 처리한다
        script_args=sys.argv[1:] if len(sys.argv) > 1 else ["build_ext", "--inplace"],
    )

    # 빌드 완료 후 .so 파일 검증을 수행한다
    if "build_ext" in sys.argv or len(sys.argv) == 1:
        verify_so_files()
        _clean_build_artifacts()

    print("\n=== Cython 컴파일 완료 ===")
    print("사용법:")
    print("  1) inplace 빌드: python setup_cython.py build_ext --inplace")
    print("  2) PyInstaller 후 교체: python -c \"from setup_cython import post_build; post_build('dist/StockTrading')\"")
