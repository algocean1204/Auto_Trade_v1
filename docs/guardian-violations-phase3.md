# Guardian Violation Report -- Phase 3 (PyInstaller Packaging)

## Phase 정보
- **Phase**: 3 (PyInstaller Packaging)
- **Phase 목표**: Python 백엔드를 macOS arm64 바이너리로 패키징
- **모니터링 일시**: 2026-03-17
- **스캔 범위**: src/ 312개 Python 파일, requirements.txt 39개 패키지, data/ + knowledge/ + alembic/

---

## 1. 필수 Hidden Imports 전체 목록

PyInstaller가 자동 감지하지 못하는 hidden import를 전수 조사한 결과이다. 
모든 lazy import (`from X import Y` inside function body)와 conditional import를 포함한다.

### 1A. 핵심 런타임 (반드시 포함)

| 패키지 | 사용 위치 | Import 패턴 | Hidden Import 필요 |
|---|---|---|---|
| `uvicorn` | api_server.py:318 | 함수 내 `import uvicorn` | `uvicorn`, `uvicorn.logging`, `uvicorn.loops`, `uvicorn.loops.auto`, `uvicorn.protocols`, `uvicorn.protocols.http`, `uvicorn.protocols.http.auto`, `uvicorn.protocols.websockets`, `uvicorn.protocols.websockets.auto`, `uvicorn.lifespan`, `uvicorn.lifespan.on` |
| `uvloop` | main.py:21 | try/except 조건부 | `uvloop` |
| `aiosqlite` | database_gateway.py (SQLAlchemy 드라이버) | SQLAlchemy URL 문자열 참조 | `aiosqlite`, `aiosqlite.context` |
| `sqlalchemy` | 15개 파일 | 직접 import | `sqlalchemy.ext.asyncio`, `sqlalchemy.dialects.sqlite`, `sqlalchemy.dialects.sqlite.aiosqlite` |
| `pydantic` | 10개+ 파일 | 직접 import | `pydantic`, `pydantic.deprecated`, `pydantic.deprecated.decorator` |
| `fastapi` | api_server.py | 직접 import | `fastapi`, `fastapi.middleware`, `fastapi.middleware.cors` |
| `dotenv` | secret_vault.py:14 | 직접 import | `dotenv` |

### 1B. AI/ML 관련 (반드시 포함 -- Metal GPU 필수)

| 패키지 | 사용 위치 | Import 패턴 | Hidden Import 필요 |
|---|---|---|---|
| `llama_cpp` | local_llm.py:48,65 | 함수 내 lazy import | `llama_cpp`, `llama_cpp.llama`, `llama_cpp.llama_cpp` |
| `chromadb` | knowledge_manager.py:26 | 함수 내 lazy import | `chromadb`, `chromadb.api`, `chromadb.config`, `chromadb.db`, `chromadb.utils`, `chromadb.utils.embedding_functions` |
| `sentence_transformers` | knowledge_manager.py:42 (via chromadb) | 함수 내 lazy import | `sentence_transformers` |
| `anthropic` | api_backend.py:36 | 함수 내 lazy import | `anthropic`, `anthropic._client` |
| `hmmlearn` | micro_regime.py:40 | 함수 내 lazy import | `hmmlearn`, `hmmlearn.hmm` |
| `numpy` | 10개 파일 | 직접 import | `numpy`, `numpy.core`, `numpy._core` |
| `lightgbm` | lgbm_trainer.py:48, walk_forward.py:33, optuna_optimizer.py:20 | 함수 내 lazy import | `lightgbm` |
| `sklearn` | lgbm_trainer.py:50-51, walk_forward.py:35, optuna_optimizer.py:23-24 | 함수 내 lazy import | `sklearn`, `sklearn.model_selection`, `sklearn.metrics` |
| `optuna` | optuna_optimizer.py:22 | 함수 내 lazy import | `optuna` |
| `huggingface_hub` | model_manager.py:129 | 함수 내 lazy import | `huggingface_hub` |

### 1C. 네트워크/크롤링 (반드시 포함)

| 패키지 | 사용 위치 | Import 패턴 | Hidden Import 필요 |
|---|---|---|---|
| `aiohttp` | 6개 파일 (connection.py, broker_gateway.py, http_client.py 등) | 직접 import | `aiohttp` |
| `httpx` | net_liquidity.py:98 | 함수 내 lazy import | `httpx` |
| `websockets` | connection.py | 직접 import | `websockets`, `websockets.legacy`, `websockets.legacy.client` |
| `feedparser` | rss_crawler.py:13 | 직접 import | `feedparser` |

### 1D. 텔레그램 (반드시 포함)

| 패키지 | 사용 위치 | Import 패턴 | Hidden Import 필요 |
|---|---|---|---|
| `telegram` | telegram_gateway.py:80-81, bot_handler.py:18-19, _setup_validators.py:101 | 함수 내 lazy import | `telegram`, `telegram.ext`, `telegram.request` |

### 1E. 암호화 (반드시 포함)

| 패키지 | 사용 위치 | Import 패턴 | Hidden Import 필요 |
|---|---|---|---|
| `Crypto` (pycryptodome) | websocket/connection.py:17-18 | 직접 import | `Crypto`, `Crypto.Cipher`, `Crypto.Cipher.AES`, `Crypto.Util`, `Crypto.Util.Padding` |

---

## 2. 필수 Data Files / Directories

### 2A. knowledge/ 디렉토리 [CRITICAL]

**requirement에 명시된 필수 포함 항목이다.**

```
knowledge/
  companies.jsonl    (5,617 bytes)
  people.jsonl       (2,414 bytes)
  products.jsonl     (4,665 bytes)
  supply_chain.jsonl (2,740 bytes)
  terms.jsonl        (6,269 bytes)
```

ChromaDB에 seed 데이터로 사용되며, PyInstaller datas에 `('knowledge', 'knowledge')` 형태로 포함해야 한다.

### 2B. alembic/ 디렉토리 [CRITICAL]

**requirement에 명시된 필수 포함 항목이다.**

```
alembic/
  env.py
  script.py.mako
  versions/
    0001_v2_clean_initial_schema.py
    0002_add_universe_config.py
    0003_rebuild_articles_v2.py
    0004_sqlite_initial.py
```

`alembic.ini`도 프로젝트 루트에서 함께 번들해야 한다.

### 2C. data/ 디렉토리 -- 템플릿/기본값 파일

번들에 포함해야 할 **초기 데이터 템플릿**이다 (런타임 생성 파일은 제외):

```
data/
  strategy_params.json          (기본 전략 파라미터)
  ticker_params.json            (티커별 기본 파라미터, 66KB)
  trading_principles.example.json  (예제 파일)
  trading_principles.json       (매매 원칙)
```

**주의**: `kis_token.json`, `kis_real_token.json`, `token_usage.json`, `server_port.txt`, `trading.db`는 런타임 생성 파일이므로 번들에 포함하지 않는다.

### 2D. agents/docs/ 디렉토리 (비필수, 선택)

`src/agents/docs/` 아래 29개 마크다운 파일. `_index.md` 포함. 에이전트 문서 표시용이므로 기능에 직접 영향 없지만, 관련 API 엔드포인트가 이를 참조하므로 포함 권장.

---

## 3. VIOLATIONS (발견된 위반 사항)

### [VIOLATION-001] Severity: P1 -- Path(__file__) 하드코딩 (PyInstaller 호환성 위반)

- **위반 유형**: PyInstaller frozen 환경에서 경로 해석 실패 가능
- **상세**: `paths.py`의 `get_data_dir()` 등 중앙 경로 관리 함수가 존재하나, 12개 파일이 `Path(__file__).resolve().parent...` 패턴으로 직접 경로를 계산한다. PyInstaller --onefile 모드에서 `__file__`은 임시 해제 디렉토리(`_MEIPASS`)를 가리키므로, `data/` 디렉토리 등 런타임 쓰기 경로가 잘못 해석될 수 있다.
- **해당 파일 목록**:
  1. `src/optimization/param_tuner/execution_optimizer.py:14` -- `Path(__file__) ... / "data" / "strategy_params.json"`
  2. `src/optimization/rag/knowledge_manager.py:33` -- `Path(__file__) ... / "data" / "chromadb"`
  3. `src/optimization/feedback/daily_report_generator.py:15` -- `Path(__file__) ... / "data" / "reports"`
  4. `src/optimization/feedback/execution_optimizer.py:17` -- `Path(__file__) ... / "data" / "strategy_params.json"`
  5. `src/optimization/ml/lgbm_trainer.py:15` -- `Path(__file__) ... / "data" / "models"`
  6. `src/agents/registry.py:13` -- `Path(__file__) ... / "docs"`
  7. `src/common/broker_gateway.py:23` -- `Path(__file__) ... / "data"`
  8. `src/common/token_tracker.py:18` -- `Path(__file__) ... / "data" / "token_usage.json"`
  9. `src/common/logger.py:16` -- `Path(__file__) ... / "logs"`
  10. `src/monitoring/endpoints/strategy.py:42` -- `Path(__file__) ... / "data" / "strategy_params.json"`
  11. `src/monitoring/endpoints/principles.py:108` -- `Path(__file__) ... / "data" / "trading_principles.json"`
  12. `src/strategy/params/strategy_params.py:13` -- `Path(__file__) ... / "data" / "strategy_params.json"`
  13. `src/strategy/params/ticker_params.py:12` -- `Path(__file__) ... / "data" / "ticker_params.json"`
- **원래 요구사항**: Binary-only distribution, PyInstaller packaging
- **수정 지시**: 이 12개 파일의 경로 계산을 모두 `src/common/paths.py`의 `get_data_dir()`, `get_project_root()`로 교체해야 한다. `paths.py`는 이미 `sys.frozen` / `_MEIPASS` 분기 로직이 구현되어 있으므로, 이를 활용하면 된다.
- **상태**: OPEN

### [VIOLATION-002] Severity: P0 -- llama-cpp-python Metal GPU 지원 확인 필요

- **위반 유형**: [CRITICAL] 요구사항 -- Metal GPU 지원이 바이너리에 포함되어야 한다
- **상세**: `local_llm.py`에서 `n_gpu_layers=-1`로 Metal 전체 오프로드를 수행한다. PyInstaller로 패키징 시 llama-cpp-python의 Metal 백엔드 공유 라이브러리(`.dylib`)가 자동으로 번들되지 않을 수 있다. 특히:
  - `llama.cpp`가 빌드하는 `libllama.dylib` (또는 `ggml-metal.metal` 셰이더 파일)
  - Metal Performance Shaders framework 참조
  - `ggml-common.h`, `ggml-metal.metal` 등 Metal 컴파일 셰이더
- **해당 파일**: `src/common/local_llm.py:53,76` (`n_gpu_layers=-1`)
- **원래 요구사항**: `[CRITICAL] Binary must include Metal GPU support for llama-cpp-python`
- **수정 지시**: PyInstaller spec의 `binaries`에 llama-cpp-python의 `.dylib` 파일을 명시적으로 포함해야 한다. 다음 명령으로 위치를 확인할 수 있다:
  ```python
  import llama_cpp
  print(llama_cpp.__file__)  # .so/.dylib 경로 확인
  # 또는
  import importlib.util
  spec = importlib.util.find_spec("llama_cpp")
  # spec.submodule_search_locations 에서 .dylib 파일 탐색
  ```
  추가로 `ggml-metal.metal` 셰이더 파일도 번들에 포함해야 Metal이 작동한다.
- **상태**: OPEN

### [VIOLATION-003] Severity: P1 -- Cython 대상 파일 크기 초과

- **위반 유형**: Cython 컴파일 대상 파일이 SRP 기준을 크게 초과한다
- **상세**: Cython으로 .so 바이너리 변환 예정인 5개 파일의 라인 수가 다음과 같다:
  - `order_manager.py`: 460줄 (200줄 제한 초과 -- Cython 컴파일 에러 가능성)
  - `entry_strategy.py`: 355줄 (200줄 제한 초과)
  - `secret_vault.py`: 209줄 (200줄 제한 근접)
  - `sdk_backend.py`: 155줄 (적정)
  - `api_backend.py`: 89줄 (적정)
- **수정 지시**: Cython 컴파일 자체는 파일 크기와 무관하게 가능하지만, `order_manager.py` (460줄)과 `entry_strategy.py` (355줄)에 복잡한 타입 어노테이션, lazy import, async/await 패턴이 있으므로 Cython 컴파일 시 호환성 테스트를 반드시 수행해야 한다. 특히:
  - `from __future__ import annotations` (PEP 604 타입 어노테이션 지연 평가)
  - async def / await 패턴
  - `TYPE_CHECKING` 조건부 import
- **상태**: OPEN

### [VIOLATION-004] Severity: P1 -- telegram 패키지 이름 충돌

- **위반 유형**: 내부 `src/telegram/` 모듈과 외부 `python-telegram-bot` 패키지의 이름 충돌
- **상세**: `main.py:9-16`에서 이미 이 문제를 인지하고 `sys.path` 조작으로 해결하고 있다. PyInstaller 번들에서는 `sys.path` 조작이 동일하게 작동하는지 보장되지 않는다. `import telegram`이 내부 `src/telegram/`을 먼저 찾으면 `python-telegram-bot`의 `telegram.Bot` 등을 import할 수 없다.
- **해당 파일**: `src/main.py:9-16`, `src/common/telegram_gateway.py:80-81`, `src/telegram/bot_handler.py:18-19`
- **수정 지시**: PyInstaller spec에서 `src/telegram/` 패키지의 frozen 모듈 이름이 `src.telegram`으로 정확히 resolve되는지 확인해야 한다. 테스트 시 `from telegram import Bot`이 정상 작동하는지 반드시 검증해야 한다.
- **상태**: OPEN

### [VIOLATION-005] Severity: P2 -- sentence-transformers / torch 대용량 번들 경고

- **위반 유형**: 바이너리 크기 폭증 위험
- **상세**: `sentence-transformers`는 `torch` (PyTorch)에 의존한다. PyTorch 전체를 번들에 포함하면 바이너리 크기가 2~5GB 이상 증가한다. `chromadb`가 `sentence_transformers`를 embedding function으로 사용하므로, 이 의존성을 어떻게 처리할지 결정이 필요하다.
  - 선택지 A: torch를 포함하여 전체 번들 (5GB+ 예상)
  - 선택지 B: chromadb RAG 기능을 외부 서비스로 분리
  - 선택지 C: torch를 exclude하고 런타임에 별도 설치 안내
- **수정 지시**: 바이너리 크기 요구사항이 없으므로 P2로 분류하나, 사용자 경험(비기술 사용자)을 고려하면 반드시 논의 필요.
- **상태**: OPEN

### [VIOLATION-006] Severity: P1 -- api_server.py의 _PORT_FILE 경로 하드코딩

- **위반 유형**: Path(__file__) 미사용, 상대 경로 직접 사용
- **상세**: `api_server.py:268`에서 `_PORT_FILE: str = "data/server_port.txt"`로 상대 경로를 직접 사용한다. PyInstaller 번들에서 CWD가 예측 불가하므로 파일 생성 위치가 달라질 수 있다.
- **해당 파일**: `src/monitoring/server/api_server.py:268`
- **수정 지시**: `paths.get_data_dir() / "server_port.txt"` 패턴으로 교체해야 한다.
- **상태**: OPEN

---

## 4. Cython 컴파일 대상 검증

### 4A. 5개 대상 파일 존재 확인 -- PASS

모든 파일이 존재하며 접근 가능하다:
- `/Users/kimtaekyu/.../src/common/secret_vault.py` (209줄)
- `/Users/kimtaekyu/.../src/common/ai_backends/sdk_backend.py` (155줄)
- `/Users/kimtaekyu/.../src/common/ai_backends/api_backend.py` (89줄)
- `/Users/kimtaekyu/.../src/executor/order/order_manager.py` (460줄)
- `/Users/kimtaekyu/.../src/strategy/entry/entry_strategy.py` (355줄)

### 4B. Cython 호환성 위험 요소

| 파일 | 위험 요소 | 심각도 |
|---|---|---|
| `secret_vault.py` | `from __future__ import annotations`, global 싱글톤 패턴, `ClassVar` | 중간 |
| `sdk_backend.py` | async/await, `from __future__ import annotations`, lazy import (`from anthropic`) | 높음 |
| `api_backend.py` | async/await, lazy import (`from anthropic`) | 높음 |
| `order_manager.py` | async/await, 460줄 복잡 로직, 다수 내부 모듈 import | 높음 |
| `entry_strategy.py` | async/await, 355줄, lazy import (`KnowledgeManager`), 복잡한 타입 어노테이션 | 높음 |

**핵심 주의**: Cython은 `async def`/`await`를 완전히 지원하지만, `from __future__ import annotations`와 함께 사용할 때 타입 평가 시점 차이로 인한 `NameError`가 발생할 수 있다. 각 파일을 개별적으로 Cython 컴파일하고 import 테스트를 수행해야 한다.

---

## 5. 소스 코드 유출 방지 검증

### 5A. 바이너리 포함 시 소스가 노출되는 항목

PyInstaller `--onefile` 또는 `--onedir` 모드에서 `.py` 파일은 `.pyc` (바이트코드)로 변환되어 포함된다. `.pyc`는 역컴파일 도구(`uncompyle6`, `decompyle3`)로 거의 원본에 가까운 소스 복원이 가능하다.

**Cython으로 보호되는 파일 (5개)**:
- secret_vault.py → `.so` (역공학 극히 어려움)
- sdk_backend.py → `.so`
- api_backend.py → `.so`
- order_manager.py → `.so`
- entry_strategy.py → `.so`

**보호되지 않는 파일 (307개)**: 나머지 모든 `.py` 파일은 `.pyc`로만 보호된다.

**권장**: `--key` 옵션(AES 암호화)을 PyInstaller spec에 적용하여 `.pyc` 파일의 추출 난이도를 높여야 한다. 단, 이것은 완벽한 보호가 아니며 결정적 역공학을 막을 수는 없다.

### 5B. Data 파일 노출

번들에 포함되는 `knowledge/*.jsonl`, `data/*.json`, `alembic/*.py` 파일은 평문 그대로 번들에 포함된다. 민감 정보가 없는지 확인이 필요하다.
- `knowledge/` -- 공개 기업/제품 정보 (보안 무관)
- `data/strategy_params.json` -- 매매 전략 파라미터 (민감)
- `data/ticker_params.json` -- 티커별 파라미터 (민감)
- `data/trading_principles.json` -- 매매 원칙 (민감)

**주의**: 전략 파라미터 파일들은 영업 비밀에 해당할 수 있다. 번들에 기본값만 포함하고, 실제 튜닝된 값은 Application Support에서 관리하는 현재 구조(`paths.py`의 `get_data_dir()`)가 적절하다.

---

## 6. target_arch='arm64' 검증

PyInstaller spec에 `target_arch='arm64'`를 명시해야 한다. 추가로:

- 현재 빌드 환경: macOS Darwin (Apple Silicon M4 Pro)
- `llama-cpp-python`은 ARM64 네이티브 빌드 필수 (Metal 지원)
- `numpy`, `scipy`, `scikit-learn` 등 C 확장도 ARM64 네이티브여야 한다
- `hmmlearn`도 C 확장 포함 (ARM64 빌드 확인 필요)
- `uvloop`도 C 확장 포함

---

## 7. 요약 -- 최종 Hidden Imports 목록 (spec 파일에 포함 필수)

```python
hiddenimports = [
    # -- 핵심 서버 --
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvloop',
    'aiosqlite',
    'aiosqlite.context',
    # -- SQLAlchemy --
    'sqlalchemy.ext.asyncio',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.dialects.sqlite.aiosqlite',
    # -- FastAPI / Pydantic --
    'fastapi',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'pydantic',
    'pydantic.deprecated',
    'pydantic.deprecated.decorator',
    'pydantic_settings',
    # -- AI / ML --
    'llama_cpp',
    'llama_cpp.llama',
    'llama_cpp.llama_cpp',
    'anthropic',
    'anthropic._client',
    'chromadb',
    'chromadb.api',
    'chromadb.config',
    'chromadb.db',
    'chromadb.utils',
    'chromadb.utils.embedding_functions',
    'sentence_transformers',
    'hmmlearn',
    'hmmlearn.hmm',
    'numpy',
    'numpy.core',
    'numpy._core',
    'lightgbm',
    'sklearn',
    'sklearn.model_selection',
    'sklearn.metrics',
    'optuna',
    'huggingface_hub',
    # -- 네트워크 --
    'aiohttp',
    'httpx',
    'websockets',
    'websockets.legacy',
    'websockets.legacy.client',
    'feedparser',
    # -- 텔레그램 --
    'telegram',
    'telegram.ext',
    'telegram.request',
    # -- 암호화 --
    'Crypto',
    'Crypto.Cipher',
    'Crypto.Cipher.AES',
    'Crypto.Util',
    'Crypto.Util.Padding',
    # -- 기타 --
    'dotenv',
    'email.utils',
    'alembic',
]
```

## 8. 요약 -- 필수 datas 목록 (spec 파일에 포함 필수)

```python
datas = [
    ('knowledge', 'knowledge'),
    ('alembic', 'alembic'),
    ('alembic.ini', '.'),
    ('data/strategy_params.json', 'data'),
    ('data/ticker_params.json', 'data'),
    ('data/trading_principles.json', 'data'),
    ('data/trading_principles.example.json', 'data'),
    ('src/agents/docs', 'src/agents/docs'),
]
```

## 9. 요약 -- 필수 binaries 목록 (Metal GPU)

```python
# llama-cpp-python Metal 백엔드 (정확한 경로는 환경에서 확인 필요)
import llama_cpp, os
llama_dir = os.path.dirname(llama_cpp.__file__)
binaries = [
    (os.path.join(llama_dir, '*.dylib'), 'llama_cpp'),
    (os.path.join(llama_dir, '*.so'), 'llama_cpp'),
    # Metal 셰이더 파일 (ggml-metal.metal)
    (os.path.join(llama_dir, '*.metal'), 'llama_cpp'),
]
```

---

## Violation Summary

| ID | Severity | 내용 | 상태 |
|---|---|---|---|
| VIOLATION-001 | P1 | Path(__file__) 하드코딩 12개 파일 -- PyInstaller 호환성 위반 | OPEN |
| VIOLATION-002 | P0 | llama-cpp-python Metal GPU .dylib/.metal 번들 누락 위험 | OPEN |
| VIOLATION-003 | P1 | Cython 대상 파일 async/await + annotations 호환성 미검증 | OPEN |
| VIOLATION-004 | P1 | src/telegram/ 과 python-telegram-bot 이름 충돌 | OPEN |
| VIOLATION-005 | P2 | sentence-transformers/torch 대용량 번들 (5GB+) 경고 | OPEN |
| VIOLATION-006 | P1 | api_server.py _PORT_FILE 상대 경로 하드코딩 | OPEN |

**P0 위반 1건 미해결 -- Phase 3 완료 전 반드시 해결 필요.**
**P1 위반 4건 미해결 -- Phase 3 완료 전 해결 권장.**
