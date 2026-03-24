# -*- mode: python ; coding: utf-8 -*-
"""trading_server.spec -- PyInstaller 빌드 설정 파일.

macOS Apple Silicon (arm64) 전용 빌드 구성이다.
--onedir 모드로 빌드하여 디버깅을 용이하게 한다.
"""
from __future__ import annotations

import os
import glob
import site

# ─────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────
# site-packages 경로를 자동으로 탐지한다
_sp = site.getsitepackages()[0]

# ─────────────────────────────────────────────
# 히든 임포트 (PyInstaller가 자동 감지하지 못하는 패키지)
# ─────────────────────────────────────────────
hidden_imports = [
    # --- 서버/이벤트 루프 ---
    'uvicorn',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvloop',

    # --- 데이터베이스 ---
    'aiosqlite',
    'sqlalchemy',
    'sqlalchemy.ext.asyncio',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.dialects.sqlite.aiosqlite',
    'alembic',
    'alembic.config',
    'alembic.command',
    'alembic.runtime',
    'alembic.runtime.migration',

    # --- 웹 프레임워크 ---
    'fastapi',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'starlette',
    'starlette.routing',
    'starlette.middleware',
    'starlette.responses',

    # --- HTTP 클라이언트 ---
    'httpx',
    'httpx._transports',
    'httpcore',
    'httpcore._async',
    'httpcore._sync',
    'aiohttp',
    'websockets',
    'certifi',  # SSL 인증서 번들 (httpx/aiohttp가 사용한다)

    # --- AI / LLM ---
    'anthropic',
    'anthropic._client',
    'llama_cpp',
    'sentence_transformers',
    'chromadb',
    'chromadb.api',
    'chromadb.api.segment',
    'chromadb.config',
    'chromadb.db',
    'chromadb.db.impl',
    'chromadb.segment',
    'chromadb.telemetry',
    'chromadb.utils.embedding_functions',
    'transformers',
    'huggingface_hub',

    # --- Apple Silicon ML ---
    'mlx',
    'mlx.core',
    'mlx.nn',
    'mlx_lm',
    'mlx_lm.utils',
    'mlx_lm.models',

    # --- ML / 통계 ---
    'hmmlearn',
    'hmmlearn.hmm',
    'sklearn',
    'sklearn.base',
    'sklearn.utils',
    'sklearn.utils._cython_blas',
    'sklearn.utils._typedefs',
    'sklearn.neighbors._partition_nodes',
    'sklearn.metrics',
    'sklearn.model_selection',
    'lightgbm',
    'scipy',
    'scipy.special',
    'scipy.linalg',
    'scipy.optimize',
    'scipy.stats',

    # --- 데이터 처리 ---
    'numpy',
    'numpy.core',
    'pandas',
    'pandas.core',

    # --- 데이터 모델 ---
    'pydantic',
    'pydantic.v1',
    'pydantic_core',
    'pydantic_settings',
    'pydantic.functional_validators',   # Pydantic V2 동적 로드 모듈이다
    'pydantic.functional_serializers',  # Pydantic V2 동적 로드 모듈이다

    # --- 텔레그램 ---
    'telegram',
    'telegram.ext',
    'telegram.request',
    'telegram._bot',

    # --- 크롤링 / 뉴스 ---
    'feedparser',

    # --- 시간대 ---
    'zoneinfo',  # ZoneInfo 타임존 지원 (14개 파일에서 사용한다)
    'tzdata',    # zoneinfo 백엔드 데이터이다

    # --- 유틸리티 ---
    'dotenv',

    # --- src 내부 모듈 (동적 임포트 대비) ---
    'src',
    'src.main',
    'src.common',
    'src.common.paths',
    'src.common.local_llm',
    'src.common.broker_gateway',
    'src.common.telegram_gateway',
    'src.common.ai_gateway',
    'src.common.ai_backends',
    'src.common.ai_backends.sdk_backend',
    'src.common.ai_backends.base',
    'src.common.secret_vault',
    'src.common.cache_gateway',
    'src.common.http_client',
    'src.common.error_handler',
    'src.common.token_tracker',
    'src.common.ticker_registry',
    'src.common.universe_persister',
    'src.common.market_clock',
    'src.monitoring',
    'src.monitoring.server',
    'src.monitoring.server.api_server',
    'src.monitoring.server.auth',
    'src.monitoring.endpoints',
    'src.monitoring.schemas',
    'src.monitoring.schemas.response_models',
    'src.monitoring.schemas.setup_schemas',
    'src.monitoring.schedulers',
    'src.monitoring.schedulers.fx_scheduler',
    'src.monitoring.crawlers',
    'src.monitoring.crawlers.fx_chain',
    'src.monitoring.crawlers.fx_fallbacks',
    'src.monitoring.crawlers.google_fx',
    'src.monitoring.crawlers.naver_fx',
    'src.monitoring.crawlers.fear_greed_fetcher',
    'src.monitoring.summary',
    'src.monitoring.websocket',
    'src.monitoring.websocket.ws_manager',
    'src.monitoring.telegram',
    'src.orchestration',
    'src.orchestration.init',
    'src.orchestration.init.dependency_injector',
    'src.orchestration.init.system_initializer',
    'src.orchestration.init.graceful_shutdown',
    'src.orchestration.init.noop_components',
    'src.orchestration.loops',
    'src.orchestration.phases',
    'src.crawlers',
    'src.analysis',
    'src.executor',
    'src.indicators',
    'src.optimization',
    'src.optimization.rag',
    'src.optimization.ml',
    'src.optimization.param_tuner',
    'src.optimization.feedback',
    'src.optimization.benchmark',
    'src.risk',
    'src.safety',
    'src.scalping',
    'src.strategy',
    'src.setup',
    'src.tax',
    'src.telegram',
    'src.websocket',
    'src.db',
    'src.db.models',
    'src.agents',
    'src.agents.registry',
    'src.agents.agent_meta',
    'src.agents.status_writer',
]

# ─────────────────────────────────────────────
# 바이너리 수집 (네이티브 공유 라이브러리)
# ─────────────────────────────────────────────
binaries = []

# llama.cpp Metal GPU 지원에 필요한 dylib 파일들을 수집한다
_llama_lib_dir = os.path.join(_sp, 'llama_cpp', 'lib')
if os.path.isdir(_llama_lib_dir):
    for dylib in glob.glob(os.path.join(_llama_lib_dir, '*.dylib')):
        binaries.append((dylib, 'llama_cpp/lib'))

# MLX Apple Silicon 가속에 필요한 바이너리를 수집한다
_mlx_lib_dir = os.path.join(_sp, 'mlx', 'lib')
if os.path.isdir(_mlx_lib_dir):
    for f in glob.glob(os.path.join(_mlx_lib_dir, '*')):
        # dylib, metallib 등 모든 바이너리를 포함한다
        if f.endswith(('.dylib', '.metallib')):
            binaries.append((f, 'mlx/lib'))

# MLX core cpython 확장 모듈을 수집한다 (Python 버전에 따라 동적 탐색)
_mlx_core_candidates = glob.glob(os.path.join(_sp, 'mlx', 'core.cpython-*-darwin.so'))
for _mlx_so in _mlx_core_candidates:
    binaries.append((_mlx_so, 'mlx'))

# ─────────────────────────────────────────────
# 데이터 파일 수집
# ─────────────────────────────────────────────
datas = [
    # RAG 지식 베이스 파일 (JSONL)
    ('knowledge', 'knowledge'),

    # Alembic DB 마이그레이션 파일
    ('alembic', 'alembic'),
    ('alembic.ini', '.'),

    # 매매 파라미터 설정 파일 (초기 시드용 -- 실행 시에는 App Support로 복사한다)
    ('data/strategy_params.json', 'data'),
    ('data/ticker_params.json', 'data'),
    ('data/trading_principles.json', 'data'),

    # 프로젝트 메타데이터 (update_checker가 버전 번호를 읽는다)
    ('pyproject.toml', '.'),

    # src 전체 Python 소스 (동적 임포트, 모듈 탐색용)
    ('src', 'src'),

    # KIS 토큰 독립 발급 스크립트 (번들 모드 토큰 발급 fallback용)
    ('scripts/issue_token.py', 'scripts'),
]

# ─────────────────────────────────────────────
# Analysis 설정
# ─────────────────────────────────────────────
a = Analysis(
    ['src/main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 테스트/개발 전용 패키지는 번들에서 제외한다
    excludes=[
        'pytest',
        'pytest_asyncio',
        'pytest_cov',
        'mypy',
        'ruff',
        'coverage',
        'playwright',
        '_pytest',
        'tkinter',
        'matplotlib',
    ],
    noarchive=False,
    optimize=0,
)

# ─────────────────────────────────────────────
# PYZ 아카이브 (바이트코드 압축)
# ─────────────────────────────────────────────
pyz = PYZ(a.pure)

# ─────────────────────────────────────────────
# EXE 설정
# ─────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir 모드: 바이너리를 별도 폴더에 배치한다
    name='trading_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # 디버그 심볼을 유지한다 (개발 단계)
    upx=False,  # UPX 압축을 사용하지 않는다 (Apple Silicon 호환성)
    console=True,  # 서버 프로세스이므로 콘솔 모드를 사용한다 (windowed 모드는 stdlib 임포트 문제 발생)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # None이면 현재 시스템 아키텍처로 빌드한다 (arm64/x86_64 자동 선택)
    codesign_identity='-',  # ad-hoc 서명 (개발용)
    entitlements_file=None,
)

# ─────────────────────────────────────────────
# COLLECT (onedir 번들 구성)
# ─────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,  # 디버그 심볼 유지
    upx=False,
    upx_exclude=[],
    name='trading_server',
)
