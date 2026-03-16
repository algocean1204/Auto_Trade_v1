# ClaudeClient

## 역할
Claude Opus와 Sonnet 모델 간 라우팅, 비동기 API 호출, 재시도 로직, 응답 캐싱, 토큰 사용량 추적을 제공하는 중앙 AI 클라이언트다. local 모드(Claude Code CLI)와 api 모드(Anthropic API 키) 양쪽을 지원한다.

## 소속팀
분석팀 (Analysis Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| Sonnet 모델 | claude-sonnet-4-5-20250929 | 빠른 분류/검증 태스크 |
| Opus 모델 | claude-opus-4-6 | 정확도 최우선 태스크 |
| MAX_RETRIES | 3 | API 호출 최대 재시도 횟수 |
| BASE_DELAY | 1.0초 | 지수 백오프 기본 딜레이 |
| 재시도 상태 코드 | 429, 500, 502, 503, 529 | 재시도 대상 HTTP 상태 코드 |
| Sonnet 입력 가격 | $3.0 / 1M tokens | API 모드 비용 추적용 |
| Opus 입력 가격 | $15.0 / 1M tokens | API 모드 비용 추적용 |

## 태스크-모델 라우팅
| 태스크 타입 | 모델 |
|---|---|
| news_classification | Sonnet |
| delta_analysis | Sonnet |
| crawl_verification | Sonnet |
| trading_decision | Opus |
| overnight_judgment | Opus |
| regime_detection | Opus |
| daily_feedback | Opus |
| weekly_analysis | Opus |
| continuous_analysis | Opus |

## 동작 흐름
1. `call(prompt, task_type, system_prompt)` 호출
2. `task_type` 기반으로 Sonnet/Opus 자동 선택
3. local 모드: Claude Code CLI subprocess 실행
4. api 모드: Anthropic Python SDK를 통해 API 직접 호출
5. 재시도 대상 오류 시 지수 백오프(1s, 2s, 4s) 재시도
6. 응답을 캐시에 저장 (동일 요청 방지)
7. 토큰 사용량 추적 및 비용 계산

## 입력
- `prompt`: 사용자 프롬프트 문자열
- `task_type`: 태스크 유형 (라우팅 결정)
- `system_prompt`: 시스템 프롬프트 (선택)
- `model`: 모델 직접 지정 (선택, 라우팅 우선)

## 출력
- Claude 응답 텍스트 (str)
- JSON 파싱 시 딕셔너리 반환

## 의존성
- `anthropic`: Anthropic Python SDK (api 모드)
- `subprocess`: Claude Code CLI (local 모드)
- `QuotaGuard`: API 호출 쿼터 관리 (SafetyChecker 통해 간접 연동)

## 소스 파일
`src/common/ai_gateway.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)
