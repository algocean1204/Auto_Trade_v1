# AI Auto-Trading System V2 - API Reference

## 개요

FastAPI 기반 모니터링 API 서버이다. 기본 포트는 `9500`이다.

- Base URL: `http://localhost:9500`
- 인증: 쓰기 엔드포인트는 `Authorization: Bearer <API_SECRET_KEY>` 헤더가 필요하다 (환경변수 `API_SECRET_KEY` 설정 시)
- 응답 형식: JSON
- Cache-Control: `no-store, no-cache, must-revalidate` (금융 데이터 캐싱 방지)

---

## Dashboard

### GET /dashboard/summary

대시보드 메인 요약 데이터를 반환한다.

**응답:**
```json
{
  "total_asset": 10000.0,
  "cash": 5000.0,
  "today_pnl": 150.0,
  "today_pnl_pct": 1.5,
  "cumulative_return": 1200.0,
  "active_positions": 3,
  "system_status": "NORMAL",
  "timestamp": "2026-02-19T00:00:00Z"
}
```

### GET /dashboard/charts/daily-returns

일별 수익 차트 데이터를 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| days | int | 30 | 조회 기간 (1~365) |

**응답:** `[{"date": "2026-02-18", "pnl_amount": 50.0, "pnl_pct": 0.5, "trade_count": 3}]`

### GET /dashboard/charts/cumulative

누적 수익 곡선 데이터를 반환한다.

**응답:** `[{"date": "2026-02-18", "cumulative_pnl": 1200.0}]`

### GET /dashboard/charts/heatmap/ticker

티커별 PnL 히트맵 데이터를 반환한다 (X: 날짜, Y: 티커, 색상: pnl_pct).

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| days | int | 30 | 조회 기간 (1~365) |

**응답:** `[{"x": "2026-02-18", "y": "SOXL", "value": 0.025}]`

### GET /dashboard/charts/heatmap/hourly

시간대별 성과 히트맵 데이터를 반환한다 (X: 시간, Y: 요일, 색상: avg pnl_pct).

**응답:** `[{"x": "14:00", "y": "Mon", "value": 0.015}]`

### GET /dashboard/charts/drawdown

드로다운 차트 데이터를 반환한다.

**응답:** `[{"date": "2026-02-18", "peak": 1500.0, "current": 1200.0, "drawdown_pct": 20.0}]`

---

## Indicators

### GET /indicators/weights

현재 지표 가중치와 프리셋 목록을 반환한다.

**응답:**
```json
{
  "weights": {"technical": 30, "sentiment": 25, "macro": 20, "volume": 15, "ai_signal": 10},
  "presets": ["balanced", "rsi_focused", "macro_heavy"],
  "enabled": ["rsi_7", "rsi_14", "rsi_21", "macd"]
}
```

### POST /indicators/weights

지표 가중치를 업데이트한다. 합계는 100이어야 한다.

**요청:** `{"weights": {"technical": 40, "sentiment": 20, "macro": 20, "volume": 10, "ai_signal": 10}}`

### GET /indicators/realtime/{ticker}

특정 티커의 실시간 지표 값과 최근 이력을 반환한다.

**응답:**
```json
{
  "ticker": "SOXL",
  "indicators": {
    "rsi_14": {"value": 55.3, "recorded_at": "...", "metadata": {}}
  },
  "history": [{"indicator_name": "rsi_14", "value": 55.3, "recorded_at": "..."}]
}
```

### GET /api/indicators/rsi/{ticker}

특정 티커의 Triple RSI(7/14/21) + Signal(9) 데이터를 반환한다.
레버리지 ETF 티커 입력 시 자동으로 본주 데이터를 사용한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| days | int | 100 | 데이터 기간 (10~500) |

**응답:**
```json
{
  "ticker": "SOXL",
  "analysis_ticker": "SOXX",
  "dates": ["2026-01-01", ...],
  "rsi_7": {"rsi_series": [...], "current": 62.5},
  "rsi_14": {"rsi_series": [...], "current": 55.3, "signal_series": [...]},
  "rsi_21": {"rsi_series": [...], "current": 48.7}
}
```

### PUT /api/indicators/config

지표 설정을 업데이트한다 (가중치, 활성화/비활성화, 프리셋).

**요청:**
```json
{
  "weights": {"rsi_7": 15, "rsi_14": 20},
  "enabled": {"rsi_7": true, "macd": false},
  "preset": "rsi_focused"
}
```

---

## Strategy

### GET /strategy/params

현재 전략 파라미터와 레짐 설정을 반환한다.

**응답:**
```json
{
  "params": {
    "take_profit_pct": 3.0,
    "trailing_stop_pct": 1.5,
    "stop_loss_pct": -2.0,
    "min_confidence": 0.7,
    "max_position_pct": 15.0,
    "max_daily_trades": 30,
    "vix_shutdown_threshold": 35,
    "survival_trading": {"monthly_cost_usd": 300, "enabled": true}
  },
  "regimes": {"strong_bull": {...}, "mild_bear": {...}}
}
```

### POST /strategy/params (AUTH)

전략 파라미터를 업데이트한다.

**요청:** `{"params": {"take_profit_pct": 4.0, "min_confidence": 0.75}}`

---

## Feedback

### GET /feedback/daily/{date_str}

지정 날짜의 일일 피드백 리포트를 반환한다.

**경로 파라미터:** `date_str` - YYYY-MM-DD 형식

### GET /feedback/weekly/{week_str}

지정 주의 주간 분석 리포트를 반환한다.

**경로 파라미터:** `week_str` - YYYY-WNN 형식 (예: 2026-W07)

### GET /feedback/pending-adjustments

승인 대기 중인 파라미터 조정 목록을 반환한다.

**응답:**
```json
[{
  "id": "uuid",
  "param_name": "take_profit_pct",
  "current_value": 3.0,
  "proposed_value": 3.5,
  "change_pct": 16.7,
  "reason": "최근 수익률 기반 상향 제안",
  "status": "pending",
  "created_at": "..."
}]
```

### POST /feedback/approve-adjustment/{adjustment_id}

파라미터 조정을 승인하고 적용한다.

### POST /feedback/reject-adjustment/{adjustment_id}

파라미터 조정을 거부한다.

---

## Universe

### GET /universe

전체 ETF 유니버스 목록을 반환한다.

**응답:** `[{"ticker": "SOXL", "name": "Direxion Semiconductor Bull 3X", "direction": "bull", "enabled": true}]`

### POST /universe/add

ETF 유니버스에 새 티커를 추가한다.

**요청:**
```json
{
  "ticker": "UPRO",
  "direction": "bull",
  "name": "ProShares UltraPro S&P500",
  "underlying": "SPY",
  "expense_ratio": 0.91,
  "avg_daily_volume": 5000000,
  "enabled": true
}
```

### POST /universe/toggle

티커 활성화/비활성화를 전환한다.

**요청:** `{"ticker": "SOXL", "enabled": false}`

### DELETE /universe/{ticker}

유니버스에서 티커를 제거한다.

### GET /universe/mappings

본주-레버리지 ETF 매핑 전체 목록을 반환한다.

**응답:**
```json
{
  "mappings": {
    "SPY": {"bull": "SSO", "bear": "SDS"},
    "QQQ": {"bull": "QLD", "bear": "QID"},
    "NVDA": {"bull": "NVDL", "bear": "NVDS"}
  }
}
```

### POST /universe/mappings/add

본주-레버리지 매핑을 추가한다.

**요청:** `{"underlying": "TSLA", "bull_2x": "TSLL", "bear_2x": "TSLS"}`

### DELETE /universe/mappings/{underlying}

본주-레버리지 매핑을 제거한다.

---

## Crawl

### POST /crawl/manual

수동 크롤링을 백그라운드에서 시작한다.

**응답:**
```json
{
  "task_id": "uuid",
  "status": "started",
  "message": "Crawl started in background"
}
```

### GET /crawl/status/{task_id}

크롤링 태스크의 현재 상태를 반환한다.

**응답:** `{"task_id": "uuid", "status": "running|completed|failed", "data": {...}}`

---

## System

### GET /system/status

시스템 전체 상태를 반환한다 (DB, Redis, KIS, Claude, Safety).

**응답:**
```json
{
  "timestamp": "...",
  "database": {"ok": true},
  "redis": {"ok": true},
  "kis": {"ok": true, "connected": true},
  "fallback": {"mode": "normal", "available": true},
  "quota": {"total_calls": 150},
  "safety": {"grade": "A"},
  "claude": {"status": "NORMAL"}
}
```

### GET /system/usage

API 사용량 통계를 반환한다.

**응답:**
```json
{
  "claude_calls_today": 150,
  "kis_calls_today": 0,
  "trades_today": 5,
  "crawl_articles_today": 0,
  "fallback_count": 2,
  "uptime_seconds": 3600.0
}
```

---

## Alerts

### GET /alerts

최근 알림 목록을 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| limit | int | 50 | 최대 건수 (1~200) |
| alert_type | str | null | 알림 유형 필터 |
| severity | str | null | 심각도 필터 |

### GET /alerts/unread-count

읽지 않은 알림 수를 반환한다.

### POST /alerts/{alert_id}/read

알림을 읽음으로 표시한다.

---

## Tax

### GET /tax/status

현재 연도 세금 현황을 반환한다 (양도소득세, 공제 잔여).

### GET /tax/report/{year}

연간 세금 보고서를 반환한다.

### GET /tax/harvest-suggestions

세금 손실 확정 매도 후보 포지션을 반환한다.

---

## FX (환율)

### GET /fx/status

현재 USD/KRW 환율을 반환한다.

### GET /fx/effective-return/{trade_id}

특정 거래의 환율 포함 실질수익률을 반환한다.

### GET /fx/history

환율 이력을 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| days | int | 30 | 조회 기간 (1~365) |

---

## Emergency

### POST /emergency/stop (AUTH)

긴급 정지를 발동한다. 모든 매매를 중단하고 포지션 청산을 준비한다.

### POST /emergency/resume (AUTH)

긴급 정지를 해제하고 매매를 재개한다.

### GET /emergency/status

현재 긴급 프로토콜 상태를 반환한다.

**응답:**
```json
{
  "circuit_breaker_active": false,
  "runaway_loss_shutdown": false,
  "flash_crash_cooldowns": {}
}
```

### GET /emergency/history

긴급 이벤트 이력을 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| limit | int | 50 | 최대 건수 (1~200) |

---

## Slippage

### GET /slippage/stats

슬리피지 통계를 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| ticker | str | null | 특정 종목 필터 |
| days | int | 30 | 조회 기간 (1~365) |

### GET /slippage/optimal-hours

특정 종목의 최적 체결 시간대를 반환한다.

**파라미터:**
| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| ticker | str | Y | 종목 티커 |

---

## Benchmark

### GET /benchmark/comparison

AI 전략 vs 벤치마크 (SPY, SSO) 비교 데이터를 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| period | str | weekly | daily 또는 weekly |
| lookback | int | 4 | 조회 주 수 (1~52) |

### GET /benchmark/chart

벤치마크 비교 차트 데이터를 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| days | int | 30 | 조회 기간 (1~365) |

---

## Reports

### GET /reports/daily

일일 성과 리포트를 생성하거나 조회한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| date | str | null | YYYY-MM-DD (미지정 시 오늘) |

### GET /reports/daily/list

일일 리포트 날짜 목록을 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| limit | int | 30 | 최대 날짜 수 (1~365) |

---

## News (Router: /api/news)

### GET /api/news/dates

뉴스가 존재하는 날짜 목록을 최신순으로 반환한다.

**파라미터:**
| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| limit | int | 30 | 최대 날짜 수 (1~90) |

### GET /api/news/summary

지정 날짜의 뉴스 요약을 반환한다.

### GET /api/news/daily

특정 날짜의 전체 뉴스 기사 목록을 반환한다.

### GET /api/news/{article_id}

뉴스 기사 상세를 반환한다.

---

## Macro (Router: /api/macro)

### GET /api/macro/indicators

주요 거시경제 지표(VIX, Fed Rate, CPI, 국채 스프레드 등)를 반환한다.

### GET /api/macro/series/{series_id}

특정 FRED 시계열 데이터를 반환한다.

**지원 시리즈:**
| ID | 설명 |
|----|------|
| DFF | Federal Funds Rate |
| T10Y2Y | 10Y-2Y Treasury Spread |
| VIXCLS | CBOE Volatility Index |
| CPIAUCSL | Consumer Price Index |
| UNRATE | Unemployment Rate |
| DGS10 | 10-Year Treasury Yield |
| DGS2 | 2-Year Treasury Yield |

---

## Principles (Router: /api/principles)

### GET /api/principles

전체 매매 원칙 목록을 반환한다 (시스템 원칙 + 사용자 원칙).

**응답:**
```json
{
  "core_principle": "생존 매매가 최우선이다",
  "principles": [
    {
      "id": "uuid",
      "category": "risk",
      "title": "손절은 종교이다",
      "content": "...",
      "priority": 1,
      "is_system": true,
      "enabled": true,
      "created_at": "..."
    }
  ]
}
```

### POST /api/principles

새 사용자 매매 원칙을 추가한다.

**요청:**
```json
{
  "category": "strategy",
  "title": "갭 트레이딩 원칙",
  "content": "프리마켓 갭이 2% 이상일 때만 진입한다",
  "priority": 10
}
```

### PUT /api/principles/{principle_id}

사용자 매매 원칙을 수정한다 (시스템 원칙 수정 불가).

### DELETE /api/principles/{principle_id}

사용자 매매 원칙을 삭제한다 (시스템 원칙 삭제 불가).

---

## Trade Reasoning (Router: /api/trade-reasoning)

### GET /api/trade-reasoning/dates

거래가 존재하는 날짜 목록을 반환한다.

### GET /api/trade-reasoning/daily

특정 날짜의 전체 거래 + AI 분석 근거를 반환한다.

**응답:**
```json
{
  "trades": [
    {
      "id": "uuid",
      "ticker": "SOXL",
      "direction": "buy",
      "action": "buy",
      "entry_price": 25.5,
      "exit_price": 26.2,
      "pnl_pct": 2.74,
      "reasoning": {
        "summary": "반도체 섹터 강세 + VIX 하락 추세",
        "indicator_direction": "bullish",
        "indicator_confidence": 0.85,
        "signals": [...]
      }
    }
  ]
}
```

### GET /api/trade-reasoning/stats

일별 거래 통계 요약을 반환한다.

### PUT /api/trade-reasoning/{trade_id}/feedback

거래에 사용자 피드백을 추가한다.

---

## WebSocket Channels

### WS /ws/positions

실시간 포지션 업데이트 (2초 주기).

**메시지 형식:**
```json
{
  "type": "positions",
  "data": [...],
  "timestamp": "2026-02-19T00:00:00Z"
}
```

### WS /ws/trades

실시간 매매 알림 (Redis Pub/Sub 기반).

**메시지 형식:**
```json
{
  "type": "trade_alert",
  "data": {
    "alert_type": "trade_entry",
    "ticker": "SOXL",
    "direction": "buy",
    "price": 25.5
  }
}
```

### WS /ws/crawl/{task_id}

크롤링 진행 상태 실시간 스트리밍.

**메시지 형식:**
```json
{
  "type": "crawl_progress",
  "data": {
    "status": "running",
    "source": "reuters",
    "articles_found": 15,
    "progress_pct": 45.0
  }
}
```
