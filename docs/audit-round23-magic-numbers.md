# 전수조사 Round 23: 매직넘버 + 하드코딩 설정값 탐지

## 감사 일자: 2026-03-20

---

## A. 포트 번호 하드코딩

### 결과: 문제 없음
- `9501`~`9505` 포트 범위는 `api_server.py`에 `_ALLOWED_PORTS` 리스트로 중앙 관리됨
- 셸 스크립트(`start_server.sh`, `auto_trading.sh` 등)에서 `DEFAULT_PORT=9501`로 정의 후 사용
- Dart 대시보드에서 `_allowedPorts` 상수 리스트로 관리
- Redis(6379), PostgreSQL(5432)은 `.env`/`docker-compose.yml`에서 설정 — 코드에 하드코딩 없음

---

## B. 시간 관련 매직넘버

### 결과: 일부 관찰, 대부분 적절히 상수화됨

| 항목 | 위치 | 상태 |
|------|------|------|
| 매매 자동 종료 07:00 KST | `trading_loop.py` `_AUTO_STOP_MINUTES=420` | 상수화됨 |
| 매매 마무리 05:30 KST | `trading_loop.py` `_WINDING_DOWN_MINUTES=330` | 상수화됨 |
| 매매 윈도우 20:00~06:30 | `market_clock.py` 내 시/분 리터럴 | 도메인 경계값으로 적절 |
| 세션 타입별 루프 주기 | `market_clock.py` `_LOOP_INTERVALS` dict | 상수화됨 |
| 텔레그램 재시도 딜레이 | `telegram_gateway.py` `_RETRY_DELAY=2.0` | 상수화됨 |
| HTTP 타임아웃 (10, 15초) | 각 모듈별 로컬 사용 | 각 컨텍스트에서 의미 명확 |

### 보고만 (수정 불필요)
- `market_clock.py`의 시간 경계(1200, 1230, 1410 등) — 세션 경계 정의로 도메인 상수에 해당
- 각 모듈별 `timeout=10`, `timeout=15` — 컨텍스트에 따라 다르므로 통합 불필요

---

## C. 비율/임계값 매직넘버

### 결과: 대부분 적절히 상수화됨

| 항목 | 상수명 | 위치 |
|------|--------|------|
| Beast 하드스톱 | `_BEAST_HARD_STOP_PCT` | exit_strategy.py |
| Beast 트레일링 | `_BEAST_TRAILING_ACTIVATION_PCT`, `_BEAST_TRAILING_DRAWDOWN_PCT` | exit_strategy.py |
| OBI 임계값 | `obi_threshold`, `ml_threshold` | strategy/models.py (Pydantic) |
| VIX 극단 임계값 | `_VIX_EXTREME_THRESHOLD=40.0` | safety_checker.py |
| 고영향 뉴스 임계값 | `HIGH_IMPACT_THRESHOLD=0.7` | **[수정] 3곳 중복 → 단일 소스로 통합** |
| 안전 모듈 기본값 | `SAFETY_DEFAULTS` | **[수정] 2곳 중복 → 단일 dict로 통합** |

### [수정됨] _HIGH_IMPACT_THRESHOLD 중복 (P1)
- **문제**: `news_pipeline.py`, `preparation.py`, `telegram_formatter.py` 3곳에서 동일 값 `0.7` 독립 정의
- **위험**: 한 곳만 변경 시 불일치 발생
- **수정**: `key_news_filter.py`의 `HIGH_IMPACT_THRESHOLD`를 공개 상수로 승격, 3개 파일에서 import

### [수정됨] Safety 기본값 중복 (P1)
- **문제**: `response_models.py`와 `system.py`에서 `stop_loss_pct: -2.0`, `vix_shutdown_threshold: 35` 등 8개 필드 동일 dict 중복
- **수정**: `response_models.py`에 `SAFETY_DEFAULTS` dict 정의, `system.py`에서 import

---

## D. 경로/URL 하드코딩

### [수정됨] KIS OpenAPI 베이스 URL 중복 (P0)
- **문제**: `broker_gateway.py`, `setup.py`, `_setup_validators.py`, `connection.py` 4곳에서 동일 URL 독립 정의
  - `https://openapivts.koreainvestment.com:29443`
  - `https://openapi.koreainvestment.com:9443`
- **위험**: URL 변경 시 4곳 모두 수정해야 함, 누락 시 인증 실패
- **수정**: `broker_gateway.py`에 `KIS_VIRTUAL_BASE`, `KIS_REAL_BASE` 공개 상수 정의, 나머지 3곳에서 import

### [수정됨] FRED API URL 중복 (P1)
- **문제**: `fred_fetcher.py`, `vix_fetcher.py`, `indicator_crawler.py`, `_setup_validators.py`, `net_liquidity.py` 5곳에서 동일 URL 독립 정의
  - `https://api.stlouisfed.org/fred/series/observations`
- **수정**: `fred_fetcher.py`에 `FRED_API_URL` 공개 상수 정의, 4개 파일에서 import
- **잔여**: `crawl_scheduler.py`의 `SourceConfig(url=...)` — 설정 데이터 구조이므로 유지

### [수정됨] FRED 시리즈 ID 목록 중복 (P2)
- **문제**: `fred_fetcher.py`와 `indicator_crawler.py`에서 동일 시리즈 10개를 독립 정의
- **수정**: `indicator_crawler.py`가 `fred_fetcher.FRED_SERIES`를 import

### 보고만 (수정 불필요)
- `com.stocktrader.ai` — `paths.py`에 `_BUNDLE_ID`로 상수화됨
- `com.trading.server/autotrader` — `launchagent_manager.py`에 상수화됨
- KIS WebSocket URL (`ws://ops.koreainvestment.com`) — REST API URL과 다른 도메인이므로 별도 관리 적절

---

## E. 캐시 TTL 매직넘버

### [수정됨] trading_loop.py TTL 인라인 사용 (P1)
- **문제**: `ttl=86400` (7곳), `ttl=172800` (2곳), `ttl=30` (7곳), `ttl=300` (1곳) — 총 17곳의 인라인 매직넘버
- **위험**: TTL 정책 변경 시 누락 위험, 의미 불명확
- **수정**: 모듈 상단에 TTL 상수 4개 정의
  - `_TTL_1DAY = 86400` — 일일 데이터
  - `_TTL_2DAY = 172800` — 48시간 안전 TTL
  - `_TTL_WS_STATUS = 30` — WebSocket 실시간 갱신
  - `_TTL_INDICATORS = 300` — 지표 스냅샷 (5분)

### [수정됨] fx_scheduler.py 인라인 604800 (P2)
- **문제**: `ttl=604800` (7일) 인라인 사용 — 의미 불명확
- **수정**: `_LAST_SUCCESS_TTL = 604800` 상수 추가

### 보고만 (수정 불필요)
다음은 각 모듈에서 자체 TTL 상수를 이미 잘 정의하여 사용하는 사례:
- `news_pipeline.py`: `_DAILY_CACHE_TTL`, `_HEADLINES_TTL`
- `continuous_analysis.py`: `_RESULT_TTL_SECONDS`
- `chart_data_writer.py`: `_CHART_TTL`
- `slippage_aggregator.py`: `_STATS_TTL`
- `sentinel_loop.py`: `_EMERGENCY_REPORT_TTL`, `_WATCH_TTL`, `_PRIORITY_TTL`
- `benchmark_writer.py`: `_TTL_SECONDS`
- `vix_fetcher.py`: `_VIX_TTL`
- `whale_detector.py`: `_WHALE_TTL`
- `article_dedup.py`: `_DEDUP_TTL`
- `agents/status_writer.py`: `_STATUS_TTL`, `_HISTORY_TTL`

다음은 `eod_sequence.py`와 `tax_writer.py`에서 `ttl=86400`, `ttl=86400*30` 인라인 사용이 남아있으나,
각 함수 컨텍스트에서 의미가 명확하고 EOD 전용 모듈이므로 과도한 상수화 불필요.

---

## F. 기타 매직넘버

### 보고만 (수정 불필요)
| 항목 | 위치 | 이유 |
|------|------|------|
| 알림 최대 100건 | `trading_loop.py`, `trading_control.py` | 동일 값이지만 독립 컨텍스트 |
| WS 알림 최대 50건 | `trading_loop.py` | 표시용 제한 |
| 재시도 3회 | 대부분 `_MAX_RETRIES=3` 상수화됨 | 적절 |
| 루프 주기 60초 | `cache_gateway._cleanup_expired` | 내부 구현 |
| slippage:raw 최대 500건 | `order_manager.py` | 단일 사용처 |

---

## 수정 파일 목록 (16개)

| 파일 | 변경 내용 |
|------|-----------|
| `src/common/broker_gateway.py` | `_VIRTUAL_BASE` → `KIS_VIRTUAL_BASE` 공개 상수 |
| `src/monitoring/endpoints/setup.py` | 자체 URL 정의 제거, `KIS_VIRTUAL/REAL_BASE` import |
| `src/monitoring/endpoints/_setup_validators.py` | 자체 URL 정의 → broker_gateway import, FRED URL import |
| `src/websocket/connection.py` | 승인 URL을 `KIS_*_BASE` 기반 f-string으로 변경 |
| `src/indicators/misc/fred_fetcher.py` | `_FRED_URL` → `FRED_API_URL` 공개 상수 |
| `src/indicators/misc/vix_fetcher.py` | `_FRED_URL` → `fred_fetcher.FRED_API_URL` import |
| `src/monitoring/endpoints/indicator_crawler.py` | 인라인 시리즈 목록 → `FRED_SERIES` import, URL → `FRED_API_URL` import |
| `src/risk/macro/net_liquidity.py` | 인라인 FRED URL → `FRED_API_URL` import |
| `src/analysis/classifier/key_news_filter.py` | `_DEFAULT_THRESHOLD` → `HIGH_IMPACT_THRESHOLD` 공개 상수 |
| `src/orchestration/phases/news_pipeline.py` | `_HIGH_IMPACT_THRESHOLD` → `HIGH_IMPACT_THRESHOLD` import |
| `src/orchestration/phases/preparation.py` | `_HIGH_IMPACT_THRESHOLD` → `HIGH_IMPACT_THRESHOLD` import |
| `src/orchestration/phases/telegram_formatter.py` | `_HIGH_IMPACT_THRESHOLD` → `HIGH_IMPACT_THRESHOLD` import |
| `src/monitoring/schemas/response_models.py` | `SAFETY_DEFAULTS` dict 추출, 인라인 중복 제거 |
| `src/monitoring/endpoints/system.py` | `SAFETY_DEFAULTS` import, getattr 폴백 기본값 상수화 |
| `src/orchestration/loops/trading_loop.py` | TTL 상수 4개 도입, 17곳 인라인 매직넘버 → 상수 참조 |
| `src/monitoring/schedulers/fx_scheduler.py` | `_LAST_SUCCESS_TTL=604800` 상수 추가 |
| `src/monitoring/endpoints/trading_control.py` | 알림 최대 수 매직넘버에 `_MAX_ALERTS` 로컬 상수 추가 |

---

## 요약

| 심각도 | 발견 | 수정 | 보고만 |
|--------|------|------|--------|
| P0 (일관성 위험) | 1 | 1 | 0 |
| P1 (중복 정의) | 4 | 4 | 0 |
| P2 (가독성) | 2 | 2 | 0 |
| 정보 | 12 | 0 | 12 |
| **합계** | **19** | **7** | **12** |

모든 수정 파일 구문 검사 통과 (16/16 OK).
