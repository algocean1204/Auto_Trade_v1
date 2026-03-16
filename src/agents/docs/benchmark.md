# BenchmarkComparison

## 역할
AI 전략 수익률을 SPY Buy&Hold, SSO Buy&Hold, 현금(0%)과 일/주 단위로 비교하여 스냅샷을 저장한다. 2주 연속 SPY/SSO 모두 하회 시 전략 재검토 알림을 자동 트리거한다.

## 소속팀
모니터링팀 (Monitoring Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 벤치마크 대상 | SPY, SSO, 현금(0%) | 비교 기준 |
| 언더퍼폼 임계 | 2주 연속 | SPY/SSO 모두 하회 시 알림 |
| 스냅샷 주기 | 일간/주간 | period_type 구분 |
| SPY 가격 출처 | PriceDataFetcher (yfinance) | Buy&Hold 수익률 계산 |

## 동작 흐름

### 일간 스냅샷 (record_daily_snapshot)
1. AI 전략, SPY, SSO 일간 수익률 수신
2. `ai_vs_spy_diff`, `ai_vs_sso_diff` 계산
3. `BenchmarkSnapshot` DB 기록 (daily)
4. 당일 데이터 INSERT

### 언더퍼폼 체크 (check_underperformance)
1. 최근 2주 벤치마크 스냅샷 조회
2. AI 전략이 SPY, SSO 모두 하회한 주 카운트
3. `_UNDERPERFORM_THRESHOLD_WEEKS (2)` 이상이면 알림 발송
4. AlertManager로 "전략 재검토 필요" 알림 전송

### 비교 데이터 조회 (get_comparison)
1. `period` (daily/weekly), `lookback` 기간 기준
2. DB에서 스냅샷 조회
3. 차트용 데이터 반환

### SPY/SSO 수익률 계산
- `calculate_spy_return(start_date, end_date)`: yfinance로 SPY 가격 조회
- `calculate_sso_return(start_date, end_date)`: yfinance로 SSO 가격 조회

## 입력
- `ai_return_pct`: AI 전략 일간 수익률 (DailyFeedback에서 전달)
- `spy_return_pct`: SPY Buy&Hold 일간 수익률
- `sso_return_pct`: SSO Buy&Hold 일간 수익률

## 출력
- `BenchmarkSnapshot` DB 기록
- `get_comparison()`: 비교 차트 데이터
- 언더퍼폼 감지 시 AlertManager 알림

## 의존성
- `PriceDataFetcher (yfinance)`: SPY/SSO 가격 조회
- `PostgreSQL (BenchmarkSnapshot 모델)`: 스냅샷 저장
- `AlertManager`: 언더퍼폼 알림

## 소스 파일
`src/monitoring/endpoints/benchmark.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
