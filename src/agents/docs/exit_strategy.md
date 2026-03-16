# ExitStrategy

## 역할
보유 포지션에 대해 손절, 트레일링 스탑, 익절, 보유기간 초과, EOD, VIX 긴급 등 다양한 청산 조건을 우선순위에 따라 체크하고 청산 지시를 반환한다.

## 소속팀
의사결정팀 (Decision Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| STOP_LOSS_PCT | -2.0% | 손절 기준 (진입가 대비) |
| TRAILING_STOP_PCT | 1.5% | 최고점 대비 트레일링 스탑 |
| strong_bull 익절 | 4.0% | 레짐별 익절 목표 |
| mild_bull 익절 | 3.0% | 레짐별 익절 목표 |
| sideways 익절 | 2.0% | 레짐별 익절 목표 |
| mild_bear 익절 | 2.5% | 레짐별 익절 목표 |
| crash 익절 | 1.5% | 레짐별 익절 목표 |
| day 3 청산 | 50% 부분 청산 | 보유일수 규칙 |
| day 4 청산 | 75% 부분 청산 | 보유일수 규칙 |
| day 5 청산 | 100% 강제 청산 | 보유일수 규칙 |
| VIX 긴급 임계값 | 35.0 | VIX 초과 시 즉시 전량 청산 |
| EOD 청산 | 마감 30분 전 | 당일 청산 원칙 |

## 동작 흐름
우선순위 순서로 청산 조건 체크:
1. 손절 (-2%) -> 즉시 전량 청산
2. 트레일링 스탑 (최고점 대비 -1.5%) -> 즉시 전량 청산
3. VIX 긴급 (VIX > 35) -> 즉시 전량 청산
4. 익절 (레짐별 목표%) -> 전량 청산
5. 보유일수 규칙 (day 3~5 단계적 청산)
6. EOD 청산 (마감 30분 전)
7. 청산 조건 없으면 None 반환 (보유 유지)

## 입력
- `position`: 보유 포지션 정보 (ticker, entry_price, quantity, high_price, entry_at 등)
- `current_price`: 현재 가격
- `regime`: 현재 시장 레짐
- `vix`: 현재 VIX 지수

## 출력
- 청산 신호 딕셔너리 (조건 충족 시):
  - `reason`: 청산 이유 (stop_loss/trailing_stop/take_profit/holding_days/eod/vix_emergency)
  - `side`: "sell"
  - `quantity`: 청산 수량
  - `urgency`: 긴급도
- `None`: 청산 조건 없음 (보유 유지)

## 의존성
- `StrategyParams`: 청산 파라미터 (손절, 익절, 보유기간 등)
- `MarketHours`: EOD 시간 판단 (마감 30분 전 체크)

## 소스 파일
`src/strategy/exit/exit_strategy.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
