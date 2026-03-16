# CapitalGuard

## 역할
잔액 범위 내 현물만 거래하고 신용/마진 거래를 원천 차단하는 자본금 안전 검증 모듈이다. 주문 금액이 가용 현금을 초과하거나 USD 이외 통화 주문 시 즉시 거부한다.

## 소속팀
안전팀 (Safety Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| REQUIRED_MARGIN_RATIO | 100.0% | 최소 증거금 비율 (100% 미만이면 거부) |
| ALLOWED_CURRENCY | USD | 허용 통화 (KRW 주문 즉시 거부) |
| 매도 주문 | 통화 검증만 | 매도는 자본금 초과 검증 생략 |

## 3가지 절대 규칙
1. 잔액 범위 내 현물만 거래 (주문 금액 > 가용 현금이면 거부)
2. 신용/마진 완전 금지 (증거금 비율 100% 미만이면 거부)
3. USD 전용 (KRW 주문 시도 시 즉시 거부)

## 동작 흐름
1. `validate_order(order, account_info)` 호출
2. 통화 검증 (USD만 허용)
3. 매수 주문의 경우:
   a. 증거금 비율 확인 (100% 이상만 허용)
   b. 잔액 범위 검증 (주문 금액 <= 가용 현금)
4. 매도 주문의 경우: 통화 검증만 수행
5. 모든 검증 결과를 `CapitalGuardLog` 테이블에 기록
6. `(passed: bool, reason: str)` 반환

## 입력
- `order`: 주문 정보
  - `ticker`, `side`, `quantity`, `price`, `currency` (기본 "USD")
- `account_info`: 계좌 정보
  - `cash_balance` (float, USD 가용 현금)
  - `margin_ratio` (float, 증거금 비율 %)

## 출력
- `(True, "passed")`: 주문 허용
- `(False, reason)`: 주문 거부 및 사유

## 의존성
- `PostgreSQL (CapitalGuardLog 모델)`: 검증 결과 기록

## 소스 파일
`src/safety/guards/capital_guard.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
