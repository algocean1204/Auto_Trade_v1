# KISClient

## 역할
한국투자증권 OpenAPI를 통해 해외주식 시세 조회, 주문 실행, 잔고 조회, 체결 내역 조회 기능을 제공한다. 실전/모의투자 이중 인증 구조로 모의투자 모드에서도 실전 서버의 시세를 정확하게 조회한다.

## 소속팀
실행팀 (Execution Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| MAX_RETRIES | 3 | 일시적 오류 최대 재시도 횟수 |
| RETRY_BASE_DELAY | 1.0초 | 지수 백오프 기본 딜레이 (1s, 2s, 4s) |
| 지원 거래소 | NASD/NYSE/AMEX | 나스닥, 뉴욕, 아멕스 |
| 시세 조회 TR_ID | HHDFS00000300 | 실전/모의 동일 TR_ID |
| 매수 TR_ID (실전) | JTTT1002U | 해외주식 매수 |
| 매수 TR_ID (모의) | VTTT1002U | 모의투자 매수 (V prefix) |
| KIS_VIRTUAL | 환경변수 | 모의투자 모드 여부 |
| 토큰 경로 (모의) | data/kis_token.json | 24시간 유효 토큰 영속화 |
| 토큰 경로 (실전) | data/kis_real_token.json | 실전 시세 조회용 별도 토큰 |

## 이중 인증 구조
- `trading_auth`: 모의/실전 매매용 인증 (KIS_VIRTUAL 설정에 따름)
- `real_auth`: 시세 조회 전용 실전 인증 (모의투자 서버에는 시세 API 없음)
- 시세 조회 API: 항상 `real_auth` 사용
- 매매 API: `trading_auth` 사용 (모의: V prefix TR_ID 자동 적용)

## 동작 흐름
1. 토큰 유효성 확인 (24시간 만료 체크)
2. 만료 시 새 토큰 발급 및 JSON 파일 저장
3. API 호출 (httpx 비동기 클라이언트)
4. 5xx / 네트워크 오류 시 지수 백오프 재시도
5. `rt_cd != "0"` 이면 `KISAPIError` 또는 `KISOrderError` 발생

## 주요 메서드
- `get_current_price(ticker, exchange)`: 현재가 조회
- `place_order(ticker, side, quantity, price, exchange)`: 주문 실행
- `get_balance()`: 계좌 잔고 조회
- `get_filled_orders()`: 체결 내역 조회
- `cancel_order(order_id)`: 주문 취소

## 의존성
- `KISAuth`: 인증 토큰 관리
- `httpx`: 비동기 HTTP 클라이언트
- `data/kis_token.json`: 모의투자 토큰 영속화
- `data/kis_real_token.json`: 실전 토큰 영속화

## 소스 파일
`src/executor/broker/kis_api.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
