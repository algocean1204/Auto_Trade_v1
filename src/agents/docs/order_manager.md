# OrderManager

## 역할
진입/청산 전략의 결정을 실제 KIS 주문으로 변환한다. 안전 검증(SafetyChecker) 통과 후 KIS API로 주문을 실행하고 체결 결과를 추적하여 PostgreSQL trades 테이블에 기록한다.

## 소속팀
실행팀 (Execution Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 주문 흐름 | SafetyChecker -> KIS -> DB | 3단계 순서 |
| 미체결 추적 | pending_orders dict | ticker -> 주문 정보 in-memory |
| 주문 DB | trades 테이블 | 진입/청산 모두 기록 |
| 체결 확인 | KIS 잔고 조회 | 주문 후 포지션 확인 |

## 동작 흐름

### 진입 주문 (execute_entry)
1. SafetyChecker.pre_trade_check() 호출
2. 안전 검증 실패 시 주문 거부 (이유 로깅)
3. CapitalGuard.validate_order() 로 자본금 안전 검증
4. KISClient.place_order() 로 실제 매수 주문 실행
5. 주문 ID를 `pending_orders`에 등록
6. trades 테이블에 진입 기록 INSERT

### 청산 주문 (execute_exit)
1. KISClient.place_order() 로 매도 주문 실행 (안전 검증 생략)
2. PnL 계산 (exit_price - entry_price)
3. trades 테이블 UPDATE (exit_price, exit_at, pnl_amount, pnl_pct)
4. `pending_orders`에서 제거

### 배치 처리 (execute_batch)
1. 여러 신호를 순차 처리
2. 각 신호 실행 후 결과 누적 반환

### 미체결 정리 (cancel_unfilled_orders)
1. 일정 시간 경과 후 미체결 주문 취소
2. KIS 취소 API 호출

## 입력
- `entry_signal`: 진입 신호 딕셔너리 (ticker, side, quantity, price, confidence 등)
- `exit_signal`: 청산 신호 딕셔너리 (ticker, side, quantity, reason 등)
- `portfolio`: 현재 포트폴리오 상태 (SafetyChecker에 전달)

## 출력
- 주문 실행 결과 딕셔너리 (order_id, status, filled_price, filled_quantity)

## 의존성
- `KISClient`: 실제 주문 API 호출
- `SafetyChecker`: 매매 전 안전 검증
- `CapitalGuard`: 자본금 안전 검증
- `PostgreSQL (Trade 모델)`: 주문 기록 저장

## 소스 파일
`src/executor/order/order_manager.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
