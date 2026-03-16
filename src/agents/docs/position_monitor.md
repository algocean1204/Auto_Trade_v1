# PositionMonitor

## 역할
보유 포지션을 실시간으로 추적하고 청산 조건을 감지한다. 15분 루프에서 KIS 잔고와 로컬 포지션을 동기화하며, ExitStrategy와 HardSafety를 통해 자동 청산을 실행한다.

## 소속팀
실행팀 (Execution Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 동기화 주기 | 15분 | 메인 매매 루프와 동기 |
| 포지션 저장 | positions dict (in-memory) | ticker -> 포지션 정보 |
| 청산 우선순위 | ExitStrategy 위임 | 손절 > 트레일링 > VIX > 익절 > 보유기간 > EOD |
| 하드 리밋 | HardSafety 위임 | 절대 불가침 규칙 체크 |

## 동작 흐름

### 잔고 동기화 (sync_positions)
1. KISClient.get_balance() 로 현재 잔고 조회
2. 로컬 `positions` dict와 KIS 잔고 비교
3. 신규 포지션 추가, 청산된 포지션 제거
4. 현재가 업데이트 (최고가 추적 포함, 트레일링 스탑용)

### 포지션 모니터링 (monitor_all)
1. 모든 보유 포지션에 대해 순차 처리
2. ExitStrategy.check_exit_conditions() 호출
3. 청산 신호 발생 시 OrderManager.execute_exit() 호출
4. HardSafety 하드 리밋 추가 검증
5. 모니터링 결과 목록 반환

### 포트폴리오 요약 (get_portfolio_summary)
1. KIS 잔고 조회
2. 총 자산, 현금, 포지션별 평가액 계산
3. 대시보드용 요약 반환

## 입력
- `regime`: 현재 시장 레짐 (monitor_all에 필요)
- `vix`: 현재 VIX 지수 (monitor_all에 필요)

## 출력
- `sync_positions()`: 현재 포지션 딕셔너리
- `monitor_all()`: 처리된 포지션 결과 목록 (청산 포함)
- `get_portfolio_summary()`: 총 자산, 현금, 포지션 목록

## 의존성
- `KISClient`: 잔고 및 현재가 조회
- `ExitStrategy`: 청산 조건 판단
- `OrderManager`: 청산 주문 실행
- `HardSafety`: 절대 안전 규칙 검증

## 소스 파일
`src/executor/position/position_monitor.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
