# HardSafety

## 역할
어떤 AI 판단이나 전략 결정도 위반할 수 없는 절대 불가침 안전 규칙을 적용한다. 종목당 포지션 한도, 일일 거래 횟수, 일일 손실 한도, VIX 매매 중단 등 하드 리밋을 강제한다.

## 소속팀
안전팀 (Safety Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| max_position_pct | 15.0% | 종목당 최대 포지션 비율 |
| max_total_position_pct | 80.0% | 전체 포지션 합계 최대 비율 |
| max_daily_trades | 30 | 일일 최대 거래 횟수 |
| max_daily_loss_pct | -5.0% | 일일 최대 손실 한도 (도달 시 전면 중단) |
| stop_loss_pct | -2.0% | 단일 종목 손절 기준 |
| max_hold_days | 5 | 최대 보유 일수 (초과 시 강제 청산) |
| vix_shutdown_threshold | 35 | VIX 초과 시 신규 매수 전면 중단 |

## 동작 흐름
1. `check_position_limit(order, portfolio)` - 포지션 한도 검증
2. `check_daily_loss(current_pnl_pct)` - 일일 손실 한도 체크
3. `check_vix(vix)` - VIX 임계값 초과 체크
4. `check_daily_trades()` - 일일 거래 횟수 체크
5. `check_hold_days(entry_date)` - 보유일수 초과 체크
6. 한도 초과 시 `SafetyViolationError` 발생 또는 False 반환
7. 일일 손실 한도 도달 시 `is_shutdown = True` 설정 (이후 모든 매수 차단)
8. `reset_daily()` - 자정에 일일 카운터 리셋

## 입력
- 주문 정보 (ticker, side, quantity, price)
- 포트폴리오 정보 (positions, cash, total_value)
- 현재 VIX, 현재 일일 PnL%

## 출력
- 각 체크 메서드: `(allowed: bool, reason: str)` 튜플
- `SafetyViolationError`: 절대 불가침 규칙 위반 시

## 의존성
- `StrategyParams`: 파라미터 동적 로드 (JSON 영속화 지원)

## 소스 파일
`src/safety/hard_safety/hard_safety.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
