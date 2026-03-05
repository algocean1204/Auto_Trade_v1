# AI Auto-Trading System V2 - 배포 가이드

## 시스템 요구사항

| 항목 | 최소 사양 | 권장 사양 |
|------|-----------|-----------|
| OS | macOS (Apple Silicon) | macOS (M4 Pro) |
| RAM | 16GB | 48GB |
| Python | 3.11+ | 3.12+ |
| Docker | Docker Desktop | Docker Desktop |
| Flutter | 3.x (대시보드용) | 최신 stable |

## Docker 설정

### docker-compose.yml 구성

시스템은 PostgreSQL 17(pgvector)과 Redis 7을 Docker 컨테이너로 실행한다.

```bash
# 개발 환경 시작
docker compose --profile dev up -d

# 프로덕션 환경 시작
docker compose --profile prod up -d

# 상태 확인
docker compose --profile dev ps

# 종료
docker compose --profile dev down

# 데이터 포함 종료 (주의: 모든 데이터 삭제)
docker compose --profile dev down -v
```

### 서비스 구성

| 서비스 | 이미지 | 포트 | 설명 |
|--------|--------|------|------|
| postgres | pgvector/pgvector:pg17 | 5432 | PostgreSQL 17 + pgvector |
| redis | redis:7-alpine | 6379 | Redis 7 (AOF 영속성) |

### 헬스체크

- PostgreSQL: `pg_isready -U trading` (10초 주기)
- Redis: `redis-cli ping` (10초 주기)

### 볼륨

- `postgres_data`: PostgreSQL 데이터 영속성
- `redis_data`: Redis AOF 데이터 영속성

### MLX 모델 (호스트 실행)

MLX 기반 로컬 AI(Qwen3-30B-A3B)는 Apple Silicon MPS 접근이 필요하므로 Docker 내부가 아닌 호스트 머신에서 실행한다.

## 환경변수

`.env.example`을 복사하여 `.env` 파일을 생성한다.

```bash
cp .env.example .env
```

### 필수 환경변수

| 변수명 | 설명 | 비고 |
|--------|------|------|
| KIS_REAL_APP_KEY | KIS 실전 앱 키 | KIS Developers에서 발급 |
| KIS_REAL_APP_SECRET | KIS 실전 앱 시크릿 | KIS Developers에서 발급 |
| KIS_VIRTUAL_APP_KEY | KIS 모의 앱 키 | KIS Developers에서 발급 |
| KIS_VIRTUAL_APP_SECRET | KIS 모의 앱 시크릿 | KIS Developers에서 발급 |
| KIS_REAL_ACCOUNT | 실전 계좌번호 | XXXXXXXX-XX 형식 |
| KIS_VIRTUAL_ACCOUNT | 모의 계좌번호 | XXXXXXXX-XX 형식 |
| KIS_HTS_ID | HTS ID | 홈트레이딩 시스템 아이디 |
| DB_PASSWORD | PostgreSQL 비밀번호 | 강력한 비밀번호 설정 |

### AI 관련

| 변수명 | 설명 | 비고 |
|--------|------|------|
| CLAUDE_MODE | Claude 실행 모드 | `local` (CLI) 또는 `api` |
| ANTHROPIC_API_KEY | Anthropic API 키 | api 모드일 때만 필요 |

### 데이터베이스

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| DB_HOST | PostgreSQL 호스트 | localhost |
| DB_PORT | PostgreSQL 포트 | 5432 |
| DB_USER | PostgreSQL 사용자 | trading |
| DB_PASSWORD | PostgreSQL 비밀번호 | (필수 설정) |
| DB_NAME | 데이터베이스 이름 | trading_system |
| REDIS_HOST | Redis 호스트 | localhost |
| REDIS_PORT | Redis 포트 | 6379 |
| REDIS_PASSWORD | Redis 비밀번호 | (필수 설정) |

### 크롤링 API (선택)

| 변수명 | 설명 | 비고 |
|--------|------|------|
| FINNHUB_API_KEY | Finnhub API 키 | 미설정 시 해당 소스 건너뜀 |
| ALPHAVANTAGE_API_KEY | AlphaVantage API 키 | 미설정 시 해당 소스 건너뜀 |
| FRED_API_KEY | FRED API 키 | 거시경제 지표용 |
| REDDIT_CLIENT_ID | Reddit 앱 ID | WSB, investing 크롤링 |
| REDDIT_CLIENT_SECRET | Reddit 앱 시크릿 | WSB, investing 크롤링 |
| STOCKTWITS_ACCESS_TOKEN | StockTwits 토큰 | 미설정 시 건너뜀 |
| DART_API_KEY | DART API 키 | 미국 ETF에는 불필요 |

### 알림

| 변수명 | 설명 | 비고 |
|--------|------|------|
| TELEGRAM_BOT_TOKEN | 텔레그램 봇 토큰 | BotFather에서 발급 |
| TELEGRAM_CHAT_ID | 텔레그램 채팅 ID | 주 수신자 |
| TELEGRAM_BOT_TOKEN_2 | 텔레그램 봇 토큰 2 | 보조 수신자 (선택) |
| TELEGRAM_CHAT_ID_2 | 텔레그램 채팅 ID 2 | 보조 수신자 (선택) |

### 매매 설정

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| KIS_MODE | KIS 모드 | virtual |
| TRADING_MODE | 매매 모드 | paper |
| LOG_LEVEL | 로그 레벨 | INFO |
| API_PORT | API 서버 포트 | 9500 |
| API_SECRET_KEY | API 인증 키 | (비어 있으면 인증 비활성화) |

## macOS LaunchAgent 자동화

### 개요

macOS LaunchAgent를 사용하여 매일 23:00 KST에 자동 시작하고 06:30 KST에 자동 종료한다.

### 설치

```bash
./scripts/install_launchagent.sh install
```

### 관리 명령

```bash
# 상태 확인
./scripts/install_launchagent.sh status

# 수동 시작
./scripts/install_launchagent.sh start

# 중지
./scripts/install_launchagent.sh stop

# 제거
./scripts/install_launchagent.sh uninstall
```

### 실행 흐름 (auto_trading.sh)

```
23:00 KST  LaunchAgent 트리거
     │
     ├── 네트워크 연결 확인 (최대 30회 재시도)
     ├── Docker Desktop 확인/시작
     ├── Docker Compose 서비스 시작 (PostgreSQL, Redis)
     ├── Docker 헬스체크 통과 대기
     ├── .venv 가상환경 활성화
     ├── CLAUDECODE 환경변수 제거 (중첩 세션 방지)
     └── python3 -m src.main 실행
           │
           ├── 1분 주기 프로세스 감시
           ├── 비정상 종료 시 자동 재시작
           └── 06:30 KST 도달 시 SIGTERM 전송 → 종료
```

### 로그 위치

| 로그 | 경로 |
|------|------|
| LaunchAgent 로그 | `~/Library/Logs/trading/auto_trading.log` |
| 트레이딩 stdout | `~/Library/Logs/trading/trading_stdout.log` |
| 트레이딩 stderr | `~/Library/Logs/trading/trading_stderr.log` |
| PID 파일 | `~/Library/Logs/trading/trading.pid` |

## 프로세스 관리 스크립트

### scripts/run_trading_system.sh

수동으로 트레이딩 시스템을 실행하는 스크립트이다.

```bash
./scripts/run_trading_system.sh
```

- 가상환경 자동 활성화
- Docker 컨테이너 상태 확인 및 시작
- 의존성 자동 설치
- 시스템 실행

### scripts/auto_trading.sh

LaunchAgent가 호출하는 야간 자동매매 스크립트이다.

- 23:00~06:30 KST 운영
- 네트워크/Docker 자동 시작
- 프로세스 감시 및 자동 재시작
- Graceful shutdown

## 헬스 모니터링

### API 헬스 체크

```bash
# 시스템 상태 확인
curl http://localhost:9500/system/status

# 사용량 확인
curl http://localhost:9500/system/usage
```

### 응답 예시

```json
{
  "timestamp": "2026-02-19T00:00:00Z",
  "database": {"ok": true},
  "redis": {"ok": true},
  "kis": {"ok": true, "connected": true},
  "fallback": {"mode": "normal", "available": true},
  "safety": {"grade": "A"},
  "claude": {"status": "NORMAL"}
}
```

### Docker 헬스 체크

```bash
# 컨테이너 상태
docker compose --profile dev ps

# PostgreSQL 접속 확인
docker compose exec postgres psql -U trading -d trading_system -c "SELECT 1;"

# Redis 접속 확인
docker compose exec redis redis-cli -a $REDIS_PASSWORD ping
```

## 데이터 백업

### PostgreSQL 백업

```bash
# 백업 생성
docker compose exec postgres pg_dump -U trading trading_system > backup_$(date +%Y%m%d).sql

# 복원
docker compose exec -T postgres psql -U trading trading_system < backup_20260219.sql
```

### 전략 파라미터 백업

```bash
cp strategy_params.json strategy_params_backup_$(date +%Y%m%d).json
cp data/trading_principles.json data/trading_principles_backup_$(date +%Y%m%d).json
```

## 모의투자 vs 실전투자

### 모의투자 (권장 시작점)

```
KIS_MODE=virtual
TRADING_MODE=paper
```

- 실제 돈을 사용하지 않는다
- 모든 기능을 테스트할 수 있다
- 충분한 검증 후 실전 전환한다

### 실전투자

```
KIS_MODE=real
TRADING_MODE=live
```

**전환 전 확인사항:**
- 모의투자 최소 1주일 이상 검증 완료
- 작은 금액으로 시작
- 손실 한도 파라미터 엄격히 설정
- 텔레그램 알림 설정 완료
- 긴급 정지 방법 숙지

## KIS API 토큰 관리

### 토큰 캐싱

KIS는 1일 1회 토큰 발급 정책이므로 토큰을 파일에 캐싱한다.

| 파일 | 용도 |
|------|------|
| data/kis_token.json | 모의투자 토큰 |
| data/kis_real_token.json | 실전투자 토큰 |

이 파일들은 `.gitignore`에 포함되어 있다.

### 이중 인증

- **실전 인증**: 가격 API 전용 (시세 조회). 모의 서버에는 가격 API가 없기 때문이다.
- **모의 인증**: 매매 API 전용 (주문 실행). TR_ID에 V 접두사를 사용한다.
