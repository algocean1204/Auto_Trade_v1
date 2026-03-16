# TelegramNotifier

## 역할
등급별(CRITICAL/WARNING/INFO) 매매 알림과 일일/주간 리포트를 2개 Telegram 계정에 동시 발송하고 notification_log 테이블에 기록한다. Bot 미설정 시 graceful degradation (로그만 남기고 에러 없음).

## 소속팀
모니터링팀 (Monitoring Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 수신자 1 | TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID | 1번 수신자 환경변수 |
| 수신자 2 | TELEGRAM_BOT_TOKEN_2 + TELEGRAM_CHAT_ID_2 | 2번 수신자 환경변수 (optional) |
| critical 이모지 | 빨간 원 | 심각도별 이모지 프리픽스 |
| warning 이모지 | 노란 원 | 심각도별 이모지 프리픽스 |
| info 이모지 | 초록 원 | 심각도별 이모지 프리픽스 |
| 발송 채널 | telegram | notification_log DB 채널명 |

## 주요 알림 메서드
| 메서드 | 설명 |
|---|---|
| `send_message(title, message, severity)` | 범용 메시지 발송 |
| `send_trade_notification(exec_result)` | 매매 체결 알림 |
| `send_daily_report(report)` | 일일 성과 리포트 |
| `send_weekly_report(analysis)` | 주간 분석 리포트 |
| `send_live_readiness(metrics)` | 실전전환 준비 완료 알림 |

## 동작 흐름
1. 설정에서 Telegram 토큰/챗ID 로드
2. 수신자 미설정 시 `_enabled = False`, 이후 모든 발송을 로그로만 처리
3. `send_message()` 호출 시 모든 수신자에게 병렬 발송 (`asyncio.gather`)
4. 심각도에 따른 이모지 프리픽스 자동 추가
5. 발송 결과를 `notification_log` 테이블에 기록
6. 발송 실패 시 로그만 남기고 에러 없이 계속 진행

## 입력
- `title`: 알림 제목
- `message`: 알림 내용
- `severity`: critical/warning/info

## 출력
- Telegram 메시지 발송 (2계정 동시)
- `NotificationLog` DB 기록

## 의존성
- `python-telegram-bot` 또는 `httpx`: Telegram Bot API 호출
- `PostgreSQL (NotificationLog 모델)`: 발송 이력 기록
- `get_settings()`: 환경변수 로드

## 소스 파일
`src/monitoring/telegram/telegram_notifier.py`

## 상태
- 활성: ✅ (Telegram 토큰 설정 시)
- 마지막 실행: (자동 업데이트)
