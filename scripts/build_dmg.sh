#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# build_dmg.sh -- StockTrader .dmg 패키지 빌드 파이프라인
#
# 전체 빌드 단계:
#   1. Cython 컴파일 (선택)
#   2. PyInstaller 빌드
#   3. Post-build: .pyc → .so 교체 (Cython 사용 시)
#   4. Flutter macOS 릴리스 빌드
#   5. .app 조립: Python 백엔드를 Flutter .app에 통합한다
#   6. Ad-hoc 코드 서명
#   7. create-dmg로 배포용 .dmg 생성
#
# 사용법:
#   ./scripts/build_dmg.sh
#   ./scripts/build_dmg.sh --version 1.0.0
#   ./scripts/build_dmg.sh --skip-cython --skip-flutter
#   ./scripts/build_dmg.sh --dry-run
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# 상수 정의
# ─────────────────────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly DASHBOARD_DIR="${PROJECT_ROOT}/dashboard"
readonly DIST_DIR="${PROJECT_ROOT}/dist"

# Flutter가 빌드하는 .app 이름 (pubspec.yaml / AppInfo.xcconfig 기반)이다
readonly FLUTTER_APP_NAME="ai_trading_dashboard"
readonly FLUTTER_BUILD_DIR="${DASHBOARD_DIR}/build/macos/Build/Products/Release"
readonly FLUTTER_APP_PATH="${FLUTTER_BUILD_DIR}/${FLUTTER_APP_NAME}.app"

# 배포용 .app 이름이다
readonly DIST_APP_NAME="StockTrader"

# PyInstaller 결과물 경로이다
readonly PYINSTALLER_DIST="${DIST_DIR}/trading_server"
readonly PYINSTALLER_SPEC="${PROJECT_ROOT}/trading_server.spec"
readonly CYTHON_SETUP="${PROJECT_ROOT}/setup_cython.py"

# ─────────────────────────────────────────────────────────────
# 기본 파라미터
# ─────────────────────────────────────────────────────────────
VERSION="0.1.0"
SKIP_CYTHON=false
SKIP_PYINSTALLER=false
SKIP_FLUTTER=false
DRY_RUN=false

# ─────────────────────────────────────────────────────────────
# 타이밍 유틸리티
# ─────────────────────────────────────────────────────────────
_step_start_time=0

step_start() {
    _step_start_time=$(date +%s)
}

# 경과 시간을 "MM분 SS초" 형식으로 출력한다
step_elapsed() {
    local end_time
    end_time=$(date +%s)
    local elapsed=$(( end_time - _step_start_time ))
    local mins=$(( elapsed / 60 ))
    local secs=$(( elapsed % 60 ))
    if [[ $mins -gt 0 ]]; then
        echo "${mins}분 ${secs}초"
    else
        echo "${secs}초"
    fi
}

# ─────────────────────────────────────────────────────────────
# 로그 유틸리티
# ─────────────────────────────────────────────────────────────
_log_info()  { echo -e "\033[1;34m[정보]\033[0m $*"; }
_log_ok()    { echo -e "\033[1;32m[완료]\033[0m $*"; }
_log_warn()  { echo -e "\033[1;33m[경고]\033[0m $*"; }
_log_error() { echo -e "\033[1;31m[오류]\033[0m $*" >&2; }
_log_step()  { echo -e "\n\033[1;36m══════════════════════════════════════════\033[0m"; \
               echo -e "\033[1;36m  $*\033[0m"; \
               echo -e "\033[1;36m══════════════════════════════════════════\033[0m"; }
_log_dry()   { echo -e "\033[1;35m[DRY-RUN]\033[0m $*"; }

# ─────────────────────────────────────────────────────────────
# 인자 파싱
# ─────────────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --version)
                VERSION="$2"
                shift 2
                ;;
            --skip-cython)
                SKIP_CYTHON=true
                shift
                ;;
            --skip-pyinstaller)
                SKIP_PYINSTALLER=true
                shift
                ;;
            --skip-flutter)
                SKIP_FLUTTER=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                _log_error "알 수 없는 옵션: $1"
                print_usage
                exit 1
                ;;
        esac
    done
}

print_usage() {
    cat <<'USAGE'
사용법: build_dmg.sh [옵션]

옵션:
  --version X.X.X     버전 번호 (기본값: 0.1.0)
  --skip-cython       Cython 컴파일 단계를 건너뛴다
  --skip-pyinstaller  PyInstaller 빌드 단계를 건너뛴다
  --skip-flutter      Flutter 빌드 단계를 건너뛴다
  --dry-run           실제 빌드 없이 로직 흐름만 확인한다
  -h, --help          이 도움말을 출력한다

예시:
  ./scripts/build_dmg.sh                          # 전체 빌드
  ./scripts/build_dmg.sh --version 1.2.3          # 버전 지정
  ./scripts/build_dmg.sh --skip-cython            # Cython 생략
  ./scripts/build_dmg.sh --skip-cython --skip-flutter  # 증분 빌드
  ./scripts/build_dmg.sh --dry-run                # 논리 흐름 확인
USAGE
}

# ─────────────────────────────────────────────────────────────
# 전제 조건 확인
# ─────────────────────────────────────────────────────────────
check_prerequisites() {
    _log_step "전제 조건 확인"

    local missing=false

    # Python 환경 확인이다
    if command -v python3 &>/dev/null; then
        _log_ok "Python3: $(python3 --version 2>&1)"
    else
        _log_error "python3을 찾을 수 없다"
        missing=true
    fi

    # PyInstaller 확인이다
    if [[ "$SKIP_PYINSTALLER" == false ]]; then
        if python3 -c "import PyInstaller" &>/dev/null; then
            _log_ok "PyInstaller: 설치됨"
        else
            _log_error "PyInstaller가 설치되어 있지 않다 (pip install pyinstaller)"
            missing=true
        fi
    fi

    # Cython 확인이다 (건너뛰지 않을 때만)
    if [[ "$SKIP_CYTHON" == false ]]; then
        if python3 -c "import Cython" &>/dev/null; then
            _log_ok "Cython: 설치됨"
        else
            _log_warn "Cython이 설치되어 있지 않다. --skip-cython 플래그를 사용하거나 pip install cython 으로 설치한다"
            missing=true
        fi
    fi

    # Flutter 확인이다
    if [[ "$SKIP_FLUTTER" == false ]]; then
        if command -v flutter &>/dev/null; then
            _log_ok "Flutter: $(flutter --version 2>&1 | head -1)"
        else
            _log_error "flutter를 찾을 수 없다"
            missing=true
        fi
    fi

    # create-dmg 확인 및 자동 설치이다
    if command -v create-dmg &>/dev/null; then
        _log_ok "create-dmg: 설치됨"
    else
        _log_warn "create-dmg가 설치되어 있지 않다. Homebrew로 설치를 시도한다..."
        if command -v brew &>/dev/null; then
            if [[ "$DRY_RUN" == true ]]; then
                _log_dry "brew install create-dmg"
            else
                brew install create-dmg
                _log_ok "create-dmg: 설치 완료"
            fi
        else
            _log_error "Homebrew가 설치되어 있지 않다. create-dmg를 수동으로 설치해야 한다"
            missing=true
        fi
    fi

    # codesign 확인이다
    if command -v codesign &>/dev/null; then
        _log_ok "codesign: 사용 가능"
    else
        _log_error "codesign을 찾을 수 없다 (Xcode Command Line Tools 필요)"
        missing=true
    fi

    # 필수 파일 존재 확인이다
    if [[ "$SKIP_PYINSTALLER" == false ]] && [[ ! -f "$PYINSTALLER_SPEC" ]]; then
        _log_error "PyInstaller spec 파일을 찾을 수 없다: ${PYINSTALLER_SPEC}"
        missing=true
    fi

    if [[ "$SKIP_CYTHON" == false ]] && [[ ! -f "$CYTHON_SETUP" ]]; then
        _log_error "Cython 설정 파일을 찾을 수 없다: ${CYTHON_SETUP}"
        missing=true
    fi

    if [[ "$missing" == true ]]; then
        _log_error "전제 조건을 충족하지 못했다. 위의 오류를 해결한 후 다시 실행한다."
        exit 1
    fi

    _log_ok "전제 조건 확인 완료"
}

# ─────────────────────────────────────────────────────────────
# 1단계: Cython 컴파일 (선택 사항)
# ─────────────────────────────────────────────────────────────
step_cython() {
    _log_step "1단계: Cython 컴파일"

    if [[ "$SKIP_CYTHON" == true ]]; then
        _log_info "Cython 컴파일을 건너뛴다 (--skip-cython)"
        return 0
    fi

    step_start

    if [[ "$DRY_RUN" == true ]]; then
        _log_dry "cd ${PROJECT_ROOT} && python3 setup_cython.py build_ext --inplace"
        _log_dry "민감 모듈 5개를 .so로 컴파일한다"
        return 0
    fi

    cd "${PROJECT_ROOT}"
    _log_info "민감 모듈 5개를 .so로 컴파일한다..."
    if ! python3 setup_cython.py build_ext --inplace; then
        _log_error "Cython 컴파일에 실패했다"
        exit 1
    fi

    _log_ok "Cython 컴파일 완료 ($(step_elapsed))"
}

# ─────────────────────────────────────────────────────────────
# 2단계: PyInstaller 빌드
# ─────────────────────────────────────────────────────────────
step_pyinstaller() {
    _log_step "2단계: PyInstaller 빌드"

    if [[ "$SKIP_PYINSTALLER" == true ]]; then
        _log_info "PyInstaller 빌드를 건너뛴다 (--skip-pyinstaller)"
        # 기존 빌드 결과물이 존재하는지 확인한다
        if [[ ! -d "$PYINSTALLER_DIST" ]]; then
            _log_error "PyInstaller 빌드 결과물이 없다: ${PYINSTALLER_DIST}"
            _log_error "--skip-pyinstaller를 사용하려면 이전 빌드 결과물이 필요하다"
            exit 1
        fi
        _log_info "기존 빌드 결과물을 사용한다: ${PYINSTALLER_DIST}"
        return 0
    fi

    step_start

    if [[ "$DRY_RUN" == true ]]; then
        _log_dry "cd ${PROJECT_ROOT} && pyinstaller trading_server.spec --clean"
        return 0
    fi

    cd "${PROJECT_ROOT}"
    _log_info "PyInstaller로 trading_server를 빌드한다..."
    pyinstaller trading_server.spec --clean

    # 빌드 결과물 확인이다
    if [[ ! -f "${PYINSTALLER_DIST}/trading_server" ]]; then
        _log_error "PyInstaller 빌드 결과물을 찾을 수 없다: ${PYINSTALLER_DIST}/trading_server"
        exit 1
    fi

    _log_ok "PyInstaller 빌드 완료 ($(step_elapsed))"
    _log_info "바이너리 크기: $(du -sh "${PYINSTALLER_DIST}/trading_server" | cut -f1)"
}

# ─────────────────────────────────────────────────────────────
# 3단계: Post-build .pyc → .so 교체
# ─────────────────────────────────────────────────────────────
step_post_build() {
    _log_step "3단계: Post-build (.pyc → .so 교체)"

    if [[ "$SKIP_CYTHON" == true ]]; then
        _log_info "Cython을 건너뛰었으므로 post-build도 건너뛴다"
        return 0
    fi

    step_start

    if [[ "$DRY_RUN" == true ]]; then
        _log_dry "python3 -c \"from setup_cython import post_build; post_build('${PYINSTALLER_DIST}')\""
        _log_dry "5개 민감 모듈의 .pyc를 .so로 교체한다"
        return 0
    fi

    cd "${PROJECT_ROOT}"
    _log_info "PyInstaller 번들 내 .pyc를 .so로 교체한다..."
    python3 -c "from setup_cython import post_build; result = post_build('${PYINSTALLER_DIST}'); exit(0 if result else 1)"

    if [[ $? -ne 0 ]]; then
        _log_warn "일부 .pyc → .so 교체에 실패했다 (해당 모듈은 .pyc로 유지된다)"
    else
        _log_ok "Post-build 교체 완료 ($(step_elapsed))"
    fi
}

# ─────────────────────────────────────────────────────────────
# 4단계: Flutter macOS 릴리스 빌드
# ─────────────────────────────────────────────────────────────
step_flutter() {
    _log_step "4단계: Flutter macOS 릴리스 빌드"

    if [[ "$SKIP_FLUTTER" == true ]]; then
        _log_info "Flutter 빌드를 건너뛴다 (--skip-flutter)"
        # 기존 빌드 결과물이 존재하는지 확인한다
        if [[ ! -d "$FLUTTER_APP_PATH" ]]; then
            _log_error "Flutter 빌드 결과물이 없다: ${FLUTTER_APP_PATH}"
            _log_error "--skip-flutter를 사용하려면 이전 빌드 결과물이 필요하다"
            exit 1
        fi
        _log_info "기존 빌드 결과물을 사용한다: ${FLUTTER_APP_PATH}"
        return 0
    fi

    step_start

    if [[ "$DRY_RUN" == true ]]; then
        _log_dry "cd ${DASHBOARD_DIR} && flutter build macos --release"
        return 0
    fi

    cd "${DASHBOARD_DIR}"
    _log_info "Flutter macOS 릴리스 빌드를 시작한다..."
    flutter build macos --release

    # 빌드 결과물 확인이다
    if [[ ! -d "$FLUTTER_APP_PATH" ]]; then
        _log_error "Flutter 빌드 결과물을 찾을 수 없다: ${FLUTTER_APP_PATH}"
        exit 1
    fi

    _log_ok "Flutter 빌드 완료 ($(step_elapsed))"
    _log_info ".app 크기: $(du -sh "${FLUTTER_APP_PATH}" | cut -f1)"
}

# ─────────────────────────────────────────────────────────────
# 5단계: .app 조립 (Python 백엔드를 Flutter .app에 통합)
# ─────────────────────────────────────────────────────────────
step_assemble() {
    _log_step "5단계: .app 조립"

    local staging_dir="${DIST_DIR}/${DIST_APP_NAME}.app"
    local resources_dir="${staging_dir}/Contents/Resources"
    local python_backend_dir="${resources_dir}/python_backend"

    step_start

    if [[ "$DRY_RUN" == true ]]; then
        _log_dry "Flutter .app을 ${staging_dir}로 복사한다"
        _log_dry "PyInstaller 결과물을 ${python_backend_dir}에 복사한다"
        _log_dry "최종 구조:"
        _log_dry "  ${DIST_APP_NAME}.app/"
        _log_dry "    Contents/"
        _log_dry "      MacOS/"
        _log_dry "        ${FLUTTER_APP_NAME}   (Flutter 바이너리)"
        _log_dry "      Resources/"
        _log_dry "        python_backend/"
        _log_dry "          trading_server       (PyInstaller 바이너리)"
        _log_dry "          _internal/           (PyInstaller 종속성)"
        _log_dry "        AppIcon.icns"
        _log_dry "      Frameworks/"
        _log_dry "        ...Flutter frameworks..."
        return 0
    fi

    # 기존 스테이징 디렉토리가 있으면 제거한다
    if [[ -d "$staging_dir" ]]; then
        _log_info "기존 스테이징 .app을 제거한다..."
        rm -rf "$staging_dir"
    fi

    # Flutter .app을 스테이징 디렉토리로 복사한다
    _log_info "Flutter .app을 복사한다: ${FLUTTER_APP_PATH} → ${staging_dir}"
    cp -R "${FLUTTER_APP_PATH}" "${staging_dir}"

    # python_backend 디렉토리를 생성한다
    _log_info "python_backend 디렉토리를 생성한다..."
    mkdir -p "${python_backend_dir}"

    # PyInstaller 결과물을 python_backend에 복사한다
    _log_info "PyInstaller 결과물을 복사한다..."
    cp "${PYINSTALLER_DIST}/trading_server" "${python_backend_dir}/"
    cp -R "${PYINSTALLER_DIST}/_internal" "${python_backend_dir}/"

    # 실행 권한을 설정한다
    chmod +x "${python_backend_dir}/trading_server"

    # 조립 결과를 확인한다
    _log_info "조립된 .app 구조:"
    echo "  ${DIST_APP_NAME}.app/Contents/"
    echo "    MacOS/"
    ls "${staging_dir}/Contents/MacOS/" | while read f; do echo "      $f"; done
    echo "    Resources/"
    ls "${resources_dir}/" | while read f; do echo "      $f"; done
    echo "    Resources/python_backend/"
    ls "${python_backend_dir}/" | while read f; do echo "      $f"; done
    echo "    Frameworks/"
    ls "${staging_dir}/Contents/Frameworks/" | while read f; do echo "      $f"; done

    _log_ok ".app 조립 완료 ($(step_elapsed))"
    _log_info "전체 .app 크기: $(du -sh "${staging_dir}" | cut -f1)"
}

# ─────────────────────────────────────────────────────────────
# 6단계: Ad-hoc 코드 서명
# ─────────────────────────────────────────────────────────────
step_codesign() {
    _log_step "6단계: Ad-hoc 코드 서명"

    local staging_dir="${DIST_DIR}/${DIST_APP_NAME}.app"
    local python_backend_dir="${staging_dir}/Contents/Resources/python_backend"
    local internal_dir="${python_backend_dir}/_internal"

    step_start

    if [[ "$DRY_RUN" == true ]]; then
        _log_dry "python_backend/_internal 내 .dylib, .so 파일을 서명한다"
        _log_dry "Python.framework을 서명한다 (존재 시)"
        _log_dry "trading_server 바이너리를 서명한다"
        _log_dry "전체 .app을 deep 서명한다: codesign --force --deep --sign - ${staging_dir}"
        return 0
    fi

    local signed_count=0

    # _internal 내 모든 .dylib 파일을 서명한다
    _log_info "_internal 내 .dylib 파일을 서명한다..."
    while IFS= read -r -d '' dylib; do
        codesign --force --sign - "$dylib" 2>/dev/null && ((signed_count++)) || true
    done < <(find "${internal_dir}" -name "*.dylib" -print0 2>/dev/null)
    _log_info ".dylib 서명 완료: ${signed_count}개"

    # _internal 내 모든 .so 파일을 서명한다
    local so_count=0
    _log_info "_internal 내 .so 파일을 서명한다..."
    while IFS= read -r -d '' so_file; do
        codesign --force --sign - "$so_file" 2>/dev/null && ((so_count++)) || true
    done < <(find "${internal_dir}" -name "*.so" -print0 2>/dev/null)
    _log_info ".so 서명 완료: ${so_count}개"

    # Python.framework을 서명한다 (존재 시)
    local python_fw
    python_fw=$(find "${internal_dir}" -name "Python.framework" -type d 2>/dev/null | head -1)
    if [[ -n "$python_fw" ]]; then
        _log_info "Python.framework을 서명한다: ${python_fw}"
        codesign --force --deep --sign - "${python_fw}"
        _log_ok "Python.framework 서명 완료"
    else
        _log_info "Python.framework을 찾을 수 없다 (정상일 수 있음)"
    fi

    # Python 바이너리를 서명한다 (standalone 방식)
    local python_bin
    python_bin=$(find "${internal_dir}" -name "python3*" -type f -perm +111 2>/dev/null | head -1)
    if [[ -n "$python_bin" ]]; then
        _log_info "Python 바이너리를 서명한다: ${python_bin}"
        codesign --force --sign - "${python_bin}"
    fi

    # trading_server 바이너리를 서명한다
    _log_info "trading_server 바이너리를 서명한다..."
    codesign --force --sign - "${python_backend_dir}/trading_server"
    _log_ok "trading_server 서명 완료"

    # Flutter Frameworks를 서명한다
    _log_info "Flutter Frameworks를 서명한다..."
    local fw_dir="${staging_dir}/Contents/Frameworks"
    if [[ -d "$fw_dir" ]]; then
        while IFS= read -r -d '' fw; do
            codesign --force --deep --sign - "$fw" 2>/dev/null || true
        done < <(find "${fw_dir}" -name "*.framework" -type d -print0 2>/dev/null)
        _log_ok "Flutter Frameworks 서명 완료"
    fi

    # 전체 .app을 deep 서명한다
    _log_info "전체 .app을 deep 서명한다..."
    codesign --force --deep --sign - "${staging_dir}"

    # 서명 검증이다
    _log_info "코드 서명을 검증한다..."
    if codesign --verify --deep --strict "${staging_dir}" 2>/dev/null; then
        _log_ok "코드 서명 검증 통과"
    else
        _log_warn "코드 서명 검증에 경고가 있다 (ad-hoc 서명에서는 정상일 수 있음)"
    fi

    _log_ok "코드 서명 완료 ($(step_elapsed)), 서명된 파일: $((signed_count + so_count))개"
}

# ─────────────────────────────────────────────────────────────
# 7단계: .dmg 생성
# ─────────────────────────────────────────────────────────────
step_create_dmg() {
    _log_step "7단계: .dmg 생성"

    local staging_dir="${DIST_DIR}/${DIST_APP_NAME}.app"
    local dmg_output="${DIST_DIR}/${DIST_APP_NAME}-v${VERSION}.dmg"
    local volume_name="${DIST_APP_NAME} v${VERSION}"

    step_start

    if [[ "$DRY_RUN" == true ]]; then
        _log_dry "create-dmg 옵션:"
        _log_dry "  볼륨 이름: ${volume_name}"
        _log_dry "  창 크기: 600x400"
        _log_dry "  아이콘 크기: 128"
        _log_dry "  앱 아이콘 위치: (150, 185)"
        _log_dry "  Applications 심볼릭 링크: (450, 185)"
        _log_dry "  출력: ${dmg_output}"
        return 0
    fi

    # 기존 .dmg가 있으면 제거한다
    if [[ -f "$dmg_output" ]]; then
        _log_info "기존 .dmg를 제거한다: ${dmg_output}"
        rm -f "$dmg_output"
    fi

    _log_info ".dmg를 생성한다..."
    # create-dmg는 배경 설정 실패 시 exit code 2를 반환하지만 .dmg는 정상 생성된다
    # set -e에 의한 조기 종료를 방지하기 위해 || true로 감싼다
    create-dmg \
        --volname "${volume_name}" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 128 \
        --icon "${DIST_APP_NAME}.app" 150 185 \
        --app-drop-link 450 185 \
        --no-internet-enable \
        --hide-extension "${DIST_APP_NAME}.app" \
        "${dmg_output}" \
        "${staging_dir}" || true
    if [[ ! -f "$dmg_output" ]]; then
        _log_error ".dmg 파일이 생성되지 않았다"
        exit 1
    fi

    _log_ok ".dmg 생성 완료 ($(step_elapsed))"
    _log_info "출력: ${dmg_output}"
    _log_info "크기: $(du -sh "${dmg_output}" | cut -f1)"
}

# ─────────────────────────────────────────────────────────────
# 빌드 요약 출력
# ─────────────────────────────────────────────────────────────
print_summary() {
    local dmg_output="${DIST_DIR}/${DIST_APP_NAME}-v${VERSION}.dmg"
    local staging_dir="${DIST_DIR}/${DIST_APP_NAME}.app"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  빌드 완료 요약"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  버전:        v${VERSION}"
    echo "  아키텍처:    arm64 (Apple Silicon)"

    if [[ "$DRY_RUN" == true ]]; then
        echo ""
        echo "  [DRY-RUN 모드 — 실제 빌드는 수행하지 않았다]"
    else
        echo "  .app 경로:   ${staging_dir}"
        if [[ -d "$staging_dir" ]]; then
            echo "  .app 크기:   $(du -sh "${staging_dir}" | cut -f1)"
        fi
        if [[ -f "$dmg_output" ]]; then
            echo "  .dmg 경로:   ${dmg_output}"
            echo "  .dmg 크기:   $(du -sh "${dmg_output}" | cut -f1)"
        fi
    fi

    echo ""
    echo "  빌드 단계:"
    [[ "$SKIP_CYTHON" == true ]]     && echo "    1. Cython:      건너뜀" || echo "    1. Cython:      완료"
    [[ "$SKIP_PYINSTALLER" == true ]] && echo "    2. PyInstaller: 건너뜀" || echo "    2. PyInstaller: 완료"
    echo "    3. Post-build:  $( [[ "$SKIP_CYTHON" == true ]] && echo '건너뜀' || echo '완료' )"
    [[ "$SKIP_FLUTTER" == true ]]    && echo "    4. Flutter:     건너뜀" || echo "    4. Flutter:     완료"
    echo "    5. .app 조립:   완료"
    echo "    6. 코드 서명:   완료"
    echo "    7. .dmg 생성:   완료"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ─────────────────────────────────────────────────────────────
# 메인 실행 흐름
# ─────────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    local total_start
    total_start=$(date +%s)

    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║   StockTrader .dmg 빌드 파이프라인       ║"
    echo "║   버전: v${VERSION}                            ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""

    if [[ "$DRY_RUN" == true ]]; then
        _log_warn "DRY-RUN 모드: 실제 빌드를 수행하지 않고 논리 흐름만 확인한다"
    fi

    _log_info "프로젝트 루트: ${PROJECT_ROOT}"
    _log_info "대상 아키텍처: arm64 (Apple Silicon)"

    # dist 디렉토리를 확보한다
    mkdir -p "${DIST_DIR}"

    # 빌드 파이프라인을 실행한다
    check_prerequisites
    step_cython
    step_pyinstaller
    step_post_build
    step_flutter
    step_assemble
    step_codesign
    step_create_dmg

    # 전체 소요 시간을 계산한다
    local total_end
    total_end=$(date +%s)
    local total_elapsed=$(( total_end - total_start ))
    local total_mins=$(( total_elapsed / 60 ))
    local total_secs=$(( total_elapsed % 60 ))

    print_summary

    if [[ "$DRY_RUN" == false ]]; then
        echo "  전체 소요 시간: ${total_mins}분 ${total_secs}초"
        echo ""
    fi
}

main "$@"
