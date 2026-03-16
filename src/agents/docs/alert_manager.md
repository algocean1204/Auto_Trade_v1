# AlertManager

## 역할
매매 체결, 손절/익절, 시스템 경고, 쿼터 알림 등 다양한 알림을 Redis에 영속화하고 Redis Pub/Sub을 통해 WebSocket으로 실시간 전달한다.

## 소속팀
모니터링팀 (Monitoring Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| Redis 키 | monitoring:alerts | 알림 목록 저장 키 |
| Pub/Sub 채널 | monitoring:alerts:stream | WebSocket 실시간 브로드캐스트 채널 |
| MAX_ALERTS | 500 | 최대 보관 알림 수 (LIFO 방식) |
| 심각도 | info/warning/critical | 3단계 심각도 |

## 알림 유형
| 타입 | 설명 |
|---|---|
| trade_entry | 진입 체결 |
| trade_exit | 청산 체결 |
| stop_loss | 손절 발동 |
| take_profit | 익절 발동 |
| trailing_stop | 트레일링 스탑 발동 |
| system_warning | 시스템 경고 |
| system_error | 시스템 오류 |
| quota_warning | Claude API 쿼터 경고 |
| feedback_summary | 일일 피드백 요약 |
| vix_warning | VIX 임계값 경고 |
| daily_loss | 일일 손실 한도 경고 |

## 동작 흐름
1. `send_alert(alert_type, title, message, severity, data)` 호출
2. 알림 객체 생성 (uuid4 ID, 타임스탬프)
3. Redis LPUSH로 알림 목록에 추가 (최대 500개 유지)
4. Redis PUBLISH로 실시간 WebSocket 브로드캐스트
5. `get_recent_alerts(limit, alert_type, severity)` - 필터링 조회
6. `mark_as_read(alert_id)` - 읽음 처리

## 입력
- `alert_type`: 알림 유형 문자열
- `title`: 알림 제목
- `message`: 알림 내용
- `severity`: info/warning/critical
- `data`: 추가 데이터 딕셔너리 (선택)

## 출력
- Redis에 저장된 알림 (JSON 직렬화)
- WebSocket 구독자에게 실시간 푸시

## 의존성
- `Redis`: 알림 영속화 및 Pub/Sub

## 소스 파일
`src/monitoring/endpoints/alerts.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
