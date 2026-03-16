# SafetyChecker

## 역할
QuotaGuard와 HardSafety를 통합하여 단일 안전 점검 인터페이스를 제공한다. 모든 매매 행위 전에 Claude API 쿼터, VIX 상태, 포지션 한도, 일일 거래 한도, 일일 손실 한도를 종합 검증한다.

## 소속팀
안전팀 (Safety Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 검증 체인 | QuotaGuard -> HardSafety | 쿼터 -> 하드 리밋 순서 |
| 세션 전 체크 | pre_session_check() | 시스템 시작 시 전체 점검 |
| 매매 전 체크 | pre_trade_check() | 주문 직전 종합 검증 |
| 상태 조회 | get_safety_status() | 대시보드용 현재 안전 상태 |

## 동작 흐름

### pre_session_check()
1. Claude API 연결 상태 확인 (QuotaGuard)
2. KIS 계좌 연결 상태 확인
3. 시스템 안전 등급 결정 (NORMAL/CAUTION/DANGER)

### pre_trade_check(order, portfolio, vix)
1. QuotaGuard.check() - Claude API 쿼터 잔량 확인
2. HardSafety.check_vix(vix) - VIX 임계값 확인
3. HardSafety.check_position_limit(order, portfolio) - 포지션 한도
4. HardSafety.check_daily_trades() - 일일 거래 횟수
5. HardSafety.check_daily_loss() - 일일 손실 한도
6. 모든 체크 통과 시 `{"allowed": true}` 반환
7. 하나라도 실패 시 `{"allowed": false, "reason": "..."}` 반환

### get_safety_status()
- 쿼터 사용량, 하드 리밋 상태, 안전 등급 반환
- 대시보드 /system/status 엔드포인트에서 사용

## 입력
- `order`: 주문 정보 (ticker, side, quantity, price)
- `portfolio`: 포트폴리오 정보 (positions, cash, total_value)
- `vix`: 현재 VIX 지수

## 출력
- `{"allowed": bool, "checks": {...}, "grade": "NORMAL"|"CAUTION"|"DANGER"}`

## 의존성
- `QuotaGuard`: Claude API 쿼터 관리
- `HardSafety`: 절대 안전 규칙 검증

## 소스 파일
`src/safety/hard_safety/safety_checker.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
