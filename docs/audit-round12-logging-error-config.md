# 전수조사 Round 12: 로깅 완전성 + 에러 전파 + 환경변수/설정 일관성

**조사일**: 2026-03-19
**범위**: src/ 전체 (259 Python 파일)

---

## Part 1: 로깅 완전성

### A. get_logger(__name__) 패턴 준수

| 항목 | 결과 |
|------|------|
| `get_logger(__name__)` 사용 | 모든 모듈에서 준수 |
| `print()` 사용 | src/ 내 0건 (없음) |
| `logging.getLogger()` 직접 사용 | 0건 (모두 `get_logger` 래퍼 사용) |

- `src/common/logger.py`: `TimedRotatingFileHandler` (일별 로테이션, 30일 보관)
- 로그 포맷: `[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s`
- 중복 핸들러 방지: `_configured_loggers` set으로 관리

### B. 민감 정보 로깅 점검

| 파일 | 결과 |
|------|------|
| `broker_gateway.py` | 토큰 값 미노출, 만료 시각/유형만 기록. 파일 퍼미션 0o600 |
| `system_initializer.py` | `vault.get_secret()` 결과를 생성자에 직접 전달, 로그 없음 |
| `secret_vault.py` | 키 이름만 로깅, 값 미노출 |
| `ai_backends/sdk_backend.py` | `os.environ.copy()`에서 `CLAUDECODE` 키만 제거, 자격증명 미노출 |

**결론**: 민감 정보 로깅 위험 없음

---

## Part 2: 에러 전파 완전성

### C. 무시된 예외 (`except Exception: pass`) 수정 현황

**총 발견**: 47건
**총 수정**: 47건 (전량 해결)
**잔여**: 0건

#### 수정 파일 상세

| 파일 | 수정 건수 | 내용 |
|------|-----------|------|
| `orchestration/loops/trading_loop.py` | 19건 | equity fetch, VIX fetch, beast 캐시, pyramid 캐시, 집중도 계산, 전략파라미터 로드, 페어가격 캐시, DailyLossLimiter, TiltDetector, pre_close, beast/pyramid 상태 복원, WS alerts/orderflow/indicators 캐시 |
| `orchestration/loops/continuous_analysis.py` | 5건 | sentinel:priority, sentinel:watch, news 캐시, VIX fetch |
| `orchestration/phases/eod_sequence.py` | 4건 | VIX fetch, VIX change 캐시, slippage:raw, 뉴스 캐시 키 삭제 |
| `orchestration/phases/preparation.py` | 1건 | orphan 캐시 키 삭제 |
| `monitoring/endpoints/analysis.py` | 4건 | VIX, 레짐, 포지션, 뉴스/지표 캐시 |
| `monitoring/endpoints/macro.py` | 3건 | VIX 이전값, Fear&Greed 캐시 저장/조회 |
| `monitoring/endpoints/risk.py` | 1건 | LosingStreak max_streak |
| `monitoring/endpoints/profit_target.py` | 1건 | 당일 PnL 합산 |
| `monitoring/endpoints/tax.py` | 1건 | 환율 캐시 |
| `monitoring/schedulers/fx_scheduler.py` | 1건 | 이전 환율 캐시 |
| `monitoring/websocket/ws_manager.py` | 1건 | WebSocket close |
| `monitoring/server/api_server.py` | 1건 | 포트 파일 삭제 |
| `websocket/connection.py` | 1건 | KIS WebSocket close |
| `setup/update_checker.py` | 3건 | .env URL, pkg_version, pyproject.toml |
| `executor/position/position_bootstrap.py` | 2건 | beast/pyramid 캐시 읽기 |
| `analysis/sentinel/anomaly_detector.py` | 2건 | 볼륨 포지션, 레짐 take_profit |
| `analysis/sentinel/escalation.py` | 3건 | 포지션, VIX, 긴급 컨텍스트 |
| `analysis/feedback/eod_feedback_report.py` | 1건 | 이전 피드백 로드 |
| `strategy/stat_arb/stat_arb.py` | 1건 | 진입 시각 삭제 |
| `strategy/entry/entry_strategy.py` | 1건 | ticker params 로드 |

**수정 패턴**: 모든 `except Exception: pass` → `except Exception as exc: logger.debug("설명: %s", exc)`

### D. bare `except:` 패턴

0건 발견 (없음)

### E. HTTP 에러 처리

| 항목 | 결과 |
|------|------|
| `error_handler.py` 커스텀 예외 | `TradingError` → `BrokerError(502)`, `AiError(503)`, `DataError(422)`, `SafetyError(409)` |
| FastAPI 글로벌 핸들러 | `register_exception_handlers(app)` — 모든 커스텀 예외에 대해 적절한 HTTP 상태코드 반환 |
| 엔드포인트 에러 핸들링 | `raise HTTPException` 사용 (JSONResponse 직접 반환 없음) |

### F. asyncio.gather 에러 처리

| 파일 | 위치 | `return_exceptions=True` | 판정 |
|------|------|--------------------------|------|
| `continuous_analysis.py` | L125 | 사용 | OK |
| `eod_sequence.py` | L150 | 사용 | OK |
| `eod_sequence.py` | L268 | 사용 | OK |
| `preparation.py` | L110 | 사용 | OK |
| `setup.py` | L598 | 미사용 | 허용 (try/except 래핑, 두 토큰 모두 필요) |

---

## Part 3: 환경변수/설정 일관성

### G. .env.example vs secret_vault.py 동기화

**`_MANAGED_KEYS` (secret_vault.py)**: 20개 키

| 키 | `.env.example` | `_MANAGED_KEYS` | 비고 |
|----|:-:|:-:|------|
| KIS_APP_KEY | O | O | |
| KIS_APP_SECRET | O | O | |
| KIS_ACCOUNT_NO | O | O | |
| KIS_ACCOUNT_TYPE | O | O | |
| ANTHROPIC_API_KEY | O | O | |
| TELEGRAM_BOT_TOKEN | O | O | |
| TELEGRAM_CHAT_ID | O | O | |
| FRED_API_KEY | O | O | |
| NEWSAPI_KEY | O | O | |
| FINNHUB_API_KEY | O | O | |
| BENZINGA_API_KEY | O | O | |
| GNEWS_API_KEY | O | O | |
| MARKETAUX_API_KEY | O | O | |
| ALPHA_VANTAGE_KEY | O | O | |
| REDDIT_CLIENT_ID | O | O | |
| REDDIT_CLIENT_SECRET | O | O | |
| API_SECRET_KEY | O | O | |
| DART_API_KEY | O | O | |
| TRADING_MODE | O | O | |
| STOCKTWITS_ACCESS_TOKEN | O | O | **이번 조사에서 수정** |
| SEC_USER_AGENT | X | O | 내부 전용 (정상) |
| DB_ECHO | O | X | 비밀이 아닌 설정값 (vault 관리 불필요) |
| LOG_LEVEL | O | X | 비밀이 아닌 설정값 (vault 관리 불필요) |

**수정**: `STOCKTWITS_ACCESS_TOKEN`이 `.env.example`에는 있었으나 `_MANAGED_KEYS`에 누락 → 추가 완료

### H. 포트/시간/타임아웃 일관성

#### 포트 번호

| 파일 | 포트 | 일관성 |
|------|------|--------|
| `api_server.py` | 9501-9505 (자동 탐색) | OK |
| `start_server.sh` | 9501 | OK |
| `auto_trading.sh` | localhost:9501 호출 | OK (기본 포트) |
| `server_port.txt` | 동적 기록 (Flutter 참조) | OK |

#### 매매 시간대

| 파일 | 시간대 | 일관성 |
|------|--------|--------|
| `market_clock.py` | 세션: preparation(20:00), pre_market(20:30), power_open(23:30), mid_day(00:00), power_hour(05:30), final_monitoring(06:00), eod_sequence(06:30), closed(07:00) | 기준 |
| `trading_control.py` | 매매 윈도우: 20:00~06:30 KST | OK |
| `trading_loop.py` | auto-stop: 420분 (07:00) | OK |
| `auto_trading.sh` | 23:00 start, 06:30 stop+EOD | OK |

#### 텔레그램 타임아웃

| 설정 | 값 |
|------|-----|
| connect_timeout | 10s |
| read_timeout | 15s |
| write_timeout | 15s |
| 재시도 | 3회, 딜레이 2s |

---

## 요약

| 카테고리 | 발견 건수 | 수정 건수 | 잔여 |
|----------|-----------|-----------|------|
| `except Exception: pass` 무시 패턴 | 47 | 47 | 0 |
| `except:` (bare) | 0 | - | 0 |
| `print()` 사용 | 0 | - | 0 |
| 민감 정보 로깅 | 0 | - | 0 |
| `.env.example` ↔ `_MANAGED_KEYS` 불일치 | 1 | 1 | 0 |
| 포트/시간/타임아웃 불일치 | 0 | - | 0 |
| `asyncio.gather` 미처리 | 0 | - | 0 |
| HTTP 에러 핸들링 미흡 | 0 | - | 0 |

**총 발견/수정**: 48건 발견, 48건 수정, 잔여 0건

---

## 수정 파일 목록 (22개)

1. `src/common/secret_vault.py` — STOCKTWITS_ACCESS_TOKEN 키 추가
2. `src/orchestration/loops/trading_loop.py` — 19건 silent pass → debug 로깅
3. `src/orchestration/loops/continuous_analysis.py` — 5건 silent pass → debug 로깅
4. `src/orchestration/phases/eod_sequence.py` — 4건 silent pass → debug 로깅
5. `src/orchestration/phases/preparation.py` — 1건 silent pass → debug 로깅
6. `src/monitoring/endpoints/analysis.py` — 4건 silent pass → debug 로깅
7. `src/monitoring/endpoints/macro.py` — 3건 silent pass → debug 로깅
8. `src/monitoring/endpoints/risk.py` — 1건 silent pass → debug 로깅
9. `src/monitoring/endpoints/profit_target.py` — 1건 silent pass → debug 로깅
10. `src/monitoring/endpoints/tax.py` — 1건 silent pass → debug 로깅
11. `src/monitoring/schedulers/fx_scheduler.py` — 1건 silent pass → debug 로깅
12. `src/monitoring/websocket/ws_manager.py` — 1건 silent pass → debug 로깅
13. `src/monitoring/server/api_server.py` — 1건 silent pass → debug 로깅
14. `src/websocket/connection.py` — 1건 silent pass → debug 로깅
15. `src/setup/update_checker.py` — 3건 silent pass → debug 로깅
16. `src/executor/position/position_bootstrap.py` — 2건 silent pass → debug 로깅
17. `src/analysis/sentinel/anomaly_detector.py` — 2건 silent pass → debug 로깅
18. `src/analysis/sentinel/escalation.py` — 3건 silent pass → debug 로깅
19. `src/analysis/feedback/eod_feedback_report.py` — 1건 silent pass → debug 로깅
20. `src/strategy/stat_arb/stat_arb.py` — 1건 silent pass → debug 로깅
21. `src/strategy/entry/entry_strategy.py` — 1건 silent pass → debug 로깅
