# EmergencyProtocol

## 역할
5가지 긴급 상황(플래시 크래시, 서킷 브레이커, 시스템 크래시, 네트워크 장애, 손실 폭주)에 대한 자동 대응 프로토콜을 실행한다. 각 프로토콜은 위기 감지 -> 즉시 대응 -> DB 기록 -> 알림 순서로 동작한다.

## 소속팀
안전팀 (Safety Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| FLASH_CRASH_THRESHOLD_PCT | -5.0% | 플래시 크래시 감지 임계값 (5분 내) |
| FLASH_CRASH_WINDOW_MINUTES | 5 | 플래시 크래시 감지 시간 윈도우 |
| FLASH_CRASH_COOLDOWN_HOURS | 1 | 플래시 크래시 후 쿨다운 |
| CIRCUIT_BREAKER_VIX_TRIGGER | 35.0 | 서킷 브레이커 발동 VIX |
| CIRCUIT_BREAKER_VIX_RELEASE | 30.0 | 서킷 브레이커 해제 VIX |
| CIRCUIT_BREAKER_SPY_DROP_PCT | -3.0% | SPY 일일 하락 서킷 브레이커 트리거 |
| NETWORK_BACKOFF_INTERVALS | [5, 10, 20, 40, 60]초 | 네트워크 재연결 백오프 |
| NETWORK_MAX_DISCONNECT_SECONDS | 180초 | 최대 네트워크 단절 허용 시간 |
| RUNAWAY_LOSS_THRESHOLD_PCT | -5.0% | 손실 폭주 트리거 (전면 청산) |

## 5가지 긴급 시나리오
1. **flash_crash**: 개별 종목 5분 내 -5% 이상 급락 -> 해당 종목 즉시 청산 + 1시간 쿨다운
2. **circuit_breaker**: VIX > 35 또는 SPY -3% 이상 -> 신규 매수 중단 + 타이트한 트레일링 스탑(0.5%)
3. **system_crash**: 프로그램 재시작 시 -> 미결 포지션 복원, 미체결 주문 정리
4. **network_failure**: 네트워크 끊김 감지 -> 지수 백오프 재연결, 180초 초과 시 긴급 청산
5. **runaway_loss**: 일일 손실 -5% 도달 -> 전체 포지션 즉시 청산 + 매매 완전 중단

## 입력
- 종목 가격 이력 (flash_crash 감지)
- VIX, SPY 일일 수익률 (circuit_breaker)
- 현재 포지션 목록 (긴급 청산)

## 출력
- 각 프로토콜 실행 결과 딕셔너리
- `EmergencyEvent` DB 기록

## 의존성
- `PostgreSQL (EmergencyEvent 모델)`: 이벤트 기록
- `OrderManager` (간접): 긴급 청산 실행 (caller가 처리)
- `AlertManager`: 알림 발송

## 소스 파일
`src/safety/emergency/emergency_protocol.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
