# 상세 설치 가이드

이 문서는 AI 자동매매 시스템 V2를 처음부터 설치하고 실행하는 전체 과정을 설명한다.

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [저장소 클론](#2-저장소-클론)
3. [Python 환경 설정](#3-python-환경-설정)
4. [Docker 설정 (PostgreSQL + Redis)](#4-docker-설정)
5. [환경 변수 설정](#5-환경-변수-설정)
6. [KIS OpenAPI 등록](#6-kis-openapi-등록)
7. [Claude CLI 설치](#7-claude-cli-설치)
8. [외부 API 키 등록](#8-외부-api-키-등록)
9. [Telegram 봇 설정](#9-telegram-봇-설정)
10. [데이터베이스 초기화](#10-데이터베이스-초기화)
11. [첫 실행](#11-첫-실행)
12. [Flutter 대시보드 설치](#12-flutter-대시보드-설치)
13. [LaunchAgent 자동화 설정](#13-launchagent-자동화-설정)
14. [문제 해결](#14-문제-해결)

---

## 1. 사전 요구사항

### macOS

Apple Silicon (M1 이상) Mac을 권장한다. MLX 로컬 모델이 MPS(Metal Performance Shaders)를 활용하기 때문이다.

### Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Python 3.12+

```bash
brew install python@3.12
python3 --version  # 3.12.x 확인
```

### Docker Desktop

```bash
brew install --cask docker
# Docker Desktop을 실행하고 초기 설정을 완료한다
```

### Node.js (Claude CLI 의존)

```bash
brew install node
node --version  # LTS 버전 확인
```

### Flutter (대시보드용, 선택사항)

```bash
brew install --cask flutter
flutter doctor  # macOS Desktop 지원 확인
```

---

## 2. 저장소 클론

```bash
git clone <repository-url>
cd Stock_Trading
```

---

## 3. Python 환경 설정

### 가상환경 생성 및 활성화

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 의존성 설치

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Playwright 브라우저 설치 (일부 크롤러에 필요)

```bash
playwright install chromium
```

주요 의존성 목록:

| 패키지 | 버전 | 용도 |
|--------|------|------|
| fastapi | 0.115.6 | REST API 서버 |
| uvicorn | 0.34.0 | ASGI 서버 |
| sqlalchemy | 2.0.36 | ORM (비동기) |
| asyncpg | 0.30.0 | PostgreSQL 비동기 드라이버 |
| redis | 5.2.1 | Redis 클라이언트 |
| anthropic | 0.42.0 | Claude API SDK |
| pandas | 3.0.0 | 데이터 분석 |
| pandas-ta | 0.4.71b0 | 기술적 지표 계산 |
| mlx-lm | 0.21.2 | 로컬 AI 모델 (Apple Silicon) |
| python-telegram-bot | 21.10 | 텔레그램 봇 |
| feedparser | 6.0.11 | RSS 피드 파싱 |
| beautifulsoup4 | 4.12.3 | 웹 스크래핑 |
| chromadb | 0.6.3 | 벡터 데이터베이스 (RAG) |
| sentence-transformers | 3.3.1 | 임베딩 모델 |

---

## 4. Docker 설정

### docker-compose.yml 구조

시스템은 PostgreSQL 17 (pgvector 포함)과 Redis 7을 Docker 컨테이너로 실행한다. API 서버와 매매 시스템은 호스트 머신에서 직접 실행한다 (Claude CLI가 Docker 내부에서 접근 불가능하기 때문이다).

### 개발 환경 시작

```bash
# PostgreSQL + Redis 시작
docker compose up -d

# 상태 확인
docker compose ps

# 헬스체크 확인
docker compose ps --format "table {{.Name}}\t{{.Status}}"
```

### 프로덕션 환경 (내부 네트워크)

```bash
# 외부 포트 미노출, 내부 네트워크만 사용
docker compose --profile prod-internal up -d
```

### 컨테이너 정보

| 컨테이너 | 이미지 | 포트 | 용도 |
|----------|--------|------|------|
| trading-postgres | pgvector/pgvector:pg17 | 5432 | 메인 데이터베이스 |
| trading-redis | redis:7-alpine | 6379 | 캐싱, Pub/Sub, 세션 |

### Docker 관리 명령어

```bash
# 로그 확인
docker compose logs -f postgres
docker compose logs -f redis

# 재시작
docker compose restart

# 중지 (데이터 유지)
docker compose down

# 중지 + 볼륨 삭제 (데이터 초기화)
docker compose down -v
```

---

## 5. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일의 각 변수를 설명한다.

### KIS OpenAPI 인증

```bash
# 실전투자 앱 인증 (시세 조회 + 실전 주문)
KIS_REAL_APP_KEY=<한국투자증권에서 발급받은 실전 앱키>
KIS_REAL_APP_SECRET=<한국투자증권에서 발급받은 실전 앱시크릿>

# 모의투자 앱 인증 (모의 주문)
KIS_VIRTUAL_APP_KEY=<한국투자증권에서 발급받은 모의 앱키>
KIS_VIRTUAL_APP_SECRET=<한국투자증권에서 발급받은 모의 앱시크릿>

# 매매 모드: "virtual" (모의투자, 권장) 또는 "real" (실전투자)
KIS_MODE=virtual

# HTS ID (홈트레이딩 시스템 로그인 아이디)
KIS_HTS_ID=<HTS 아이디>

# 계좌번호 (XXXXXXXX-XX 형식)
KIS_REAL_ACCOUNT=XXXXXXXX-XX      # 실전 계좌번호
KIS_VIRTUAL_ACCOUNT=XXXXXXXX-XX   # 모의 계좌번호
```

**중요**: 모의투자 서버에는 시세 조회 API가 없다. 따라서 모의투자 모드에서도 실전 앱키가 필요하다 (시세 조회용).

### Claude AI 설정

```bash
# "local" (Claude Code CLI, Max/Pro 구독 필요) 또는 "api" (Anthropic API)
CLAUDE_MODE=local

# API 모드일 때만 필요
ANTHROPIC_API_KEY=sk-ant-xxxx
```

### 데이터베이스

```bash
DB_HOST=localhost
DB_PORT=5432
DB_USER=trading
DB_PASSWORD=<강력한_비밀번호>    # 반드시 설정해야 한다
DB_NAME=trading_system
```

### Redis

```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=trading_redis_dev   # 프로덕션에서는 변경 필수
```

### 크롤러 API 키 (선택)

```bash
# 미설정 시 해당 소스를 건너뛴다. 설정할수록 더 많은 뉴스를 수집한다.
FINNHUB_API_KEY=<Finnhub에서 발급>
ALPHAVANTAGE_API_KEY=<AlphaVantage에서 발급>
FRED_API_KEY=<FRED에서 발급>          # 매크로 지표 (VIX, CPI, 금리) 필수
REDDIT_CLIENT_ID=<Reddit 앱 ID>
REDDIT_CLIENT_SECRET=<Reddit 앱 시크릿>
```

### Telegram

```bash
TELEGRAM_BOT_TOKEN=<BotFather에서 발급받은 토큰>
TELEGRAM_CHAT_ID=<수신할 채팅 ID>

# 보조 수신자 (선택)
TELEGRAM_BOT_TOKEN_2=
TELEGRAM_CHAT_ID_2=
```

### 기타 설정

```bash
# 매매 모드: paper (모의) 또는 live (실전)
TRADING_MODE=paper
LOG_LEVEL=INFO

# API 서버 포트
API_PORT=9500

# API 인증 키 (비어있으면 인증 비활성화 - 개발 환경용)
API_SECRET_KEY=
```

---

## 6. KIS OpenAPI 등록

### 6.1 한국투자증권 계좌 개설

1. [한국투자증권](https://securities.koreainvestment.com/) 웹사이트에서 계좌를 개설한다.
2. 해외주식 거래를 위한 외화증권 계좌가 필요하다.

### 6.2 OpenAPI 서비스 신청

1. [KIS Developers](https://apiportal.koreainvestment.com/) 포털에 접속한다.
2. 회원가입 후 로그인한다.
3. **API 신청** 메뉴에서 서비스를 신청한다.

### 6.3 앱 키 발급

1. **실전투자용 앱 키**: 실제 매매 + 시세 조회에 사용한다.
2. **모의투자용 앱 키**: 모의 매매 테스트에 사용한다.
3. 각각의 `APP_KEY`와 `APP_SECRET`을 `.env`에 입력한다.

### 6.4 모의투자 계좌 개설

1. KIS Developers 포털에서 **모의투자** 메뉴에 접속한다.
2. 모의투자 계좌를 개설한다.
3. 계좌번호를 `KIS_VIRTUAL_ACCOUNT`에 입력한다.

### 주의사항

- KIS 토큰은 24시간 유효하며, 1일 1회 발급 원칙이다.
- 토큰은 `data/kis_token.json`과 `data/kis_real_token.json`에 자동 캐시된다.
- 모의투자 서버에서는 지정가(limit) 주문만 가능하다. 시장가(market) 주문은 자동으로 지정가(현재가 +-0.5%)로 변환된다.
- 거래소 코드: NAS (NASDAQ), AMS (AMEX/NYSE Arca, ETF용), NYS (NYSE)

---

## 7. Claude CLI 설치

### Claude Code CLI 설치

```bash
npm install -g @anthropic-ai/claude-code
```

### 인증

```bash
claude auth login
# 브라우저에서 Anthropic 계정 로그인
```

### 모드 확인

- **local 모드** (권장): Claude Max 또는 Pro 구독이 필요하다. `CLAUDE_MODE=local`로 설정한다. 별도 API 비용이 발생하지 않는다.
- **api 모드**: Anthropic API 키가 필요하다. `CLAUDE_MODE=api`, `ANTHROPIC_API_KEY=sk-ant-xxxx`로 설정한다. 사용량에 따라 비용이 발생한다.

### 주의사항

- Claude CLI 실행 시 `CLAUDECODE` 환경변수가 설정되어 있으면 중첩 세션 오류가 발생한다. 시스템이 자동으로 해당 환경변수를 제거한다.
- Claude CLI에는 `--max-tokens` 플래그가 없다. `--output-format text`만 사용한다.

---

## 8. 외부 API 키 등록

### FRED API (필수)

VIX, CPI, 금리 등 매크로 경제 데이터를 제공한다.

1. [FRED](https://fred.stlouisfed.org/) 웹사이트에 가입한다.
2. **My Account** > **API Keys**에서 키를 발급한다.
3. `FRED_API_KEY`에 입력한다.

### Finnhub API (권장)

실시간 뉴스와 시장 데이터를 제공한다.

1. [Finnhub](https://finnhub.io/)에 가입한다.
2. 무료 플랜으로 API 키를 발급받는다.
3. `FINNHUB_API_KEY`에 입력한다.

### AlphaVantage API (선택)

추가 시장 데이터를 제공한다.

1. [AlphaVantage](https://www.alphavantage.co/)에 가입한다.
2. 무료 API 키를 발급받는다.
3. `ALPHAVANTAGE_API_KEY`에 입력한다.

### Reddit API (선택)

Reddit 투자 커뮤니티 분석용이다.

1. [Reddit 앱](https://www.reddit.com/prefs/apps)에서 앱을 생성한다.
2. 타입: `script`로 설정한다.
3. `REDDIT_CLIENT_ID`와 `REDDIT_CLIENT_SECRET`에 입력한다.

---

## 9. Telegram 봇 설정

### 9.1 봇 생성

1. Telegram에서 [@BotFather](https://t.me/BotFather)를 검색한다.
2. `/newbot` 명령어로 새 봇을 생성한다.
3. 봇 이름과 username을 입력한다.
4. 발급된 토큰을 `TELEGRAM_BOT_TOKEN`에 입력한다.

### 9.2 Chat ID 확인

1. 생성한 봇에게 아무 메시지나 보낸다.
2. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates`에 접속한다.
3. 응답에서 `chat.id` 값을 확인한다.
4. `TELEGRAM_CHAT_ID`에 입력한다.

### 9.3 봇 기능

- **알림 수신**: 매매 실행, 긴급 상황, 일일/주간 리포트 자동 발송
- **명령어 실행**: 봇에게 명령어를 보내 원격으로 시스템을 제어한다
- **듀얼 수신**: 두 번째 Telegram 계정으로도 동시 알림을 받을 수 있다

---

## 10. 데이터베이스 초기화

### 자동 초기화

Docker Compose로 PostgreSQL을 처음 시작하면 `db/init.sql`이 자동으로 실행되어 전체 스키마가 생성된다.

```bash
docker compose up -d
# init.sql이 자동 실행된다
```

### Alembic 마이그레이션 (스키마 변경 시)

```bash
# 현재 마이그레이션 상태 확인
alembic current

# 최신으로 마이그레이션
alembic upgrade head
```

### DB 접속 확인

```bash
# psql로 직접 접속
docker exec -it trading-postgres psql -U trading -d trading_system

# 테이블 확인
\dt
```

### 주요 테이블 (20개)

| 테이블 | 설명 |
|--------|------|
| `trades` | 매매 기록 (진입/청산 가격, PnL, AI 신뢰도) |
| `articles` | 뉴스 기사 (30개 소스, 한국어 번역/요약 포함) |
| `etf_universe` | ETF 유니버스 (활성/비활성, 레버리지 정보) |
| `rag_documents` | RAG 문서 (벡터 임베딩 포함) |
| `indicator_history` | 기술적 지표 이력 |
| `feedback_reports` | 일일/주간 피드백 리포트 |
| `tax_records` | 세금 기록 (USD/KRW 환율 포함) |
| `fx_rates` | 환율 이력 |
| `slippage_log` | 슬리피지 기록 |
| `emergency_events` | 긴급 프로토콜 이벤트 |
| `benchmark_snapshots` | AI vs SPY/SSO 벤치마크 |
| `capital_guard_log` | 자본금 보호 검증 로그 |
| `notification_log` | 알림 발송 이력 |
| `profit_targets` | 월별 수익 목표 |
| `daily_pnl_log` | 일별 손익 기록 |
| `risk_config` | 리스크 설정 (key-value) |
| `risk_events` | 리스크 이벤트 기록 |
| `backtest_results` | 백테스트 결과 |
| `fear_greed_history` | Fear & Greed 지수 이력 |
| `prediction_markets` | 예측 시장 데이터 |

---

## 11. 첫 실행

### 전체 시스템 시작

```bash
source .venv/bin/activate

# Docker 서비스 확인
docker compose ps

# 시스템 시작
python -m src.main
```

시작 시 다음 순서로 초기화가 진행된다:

1. DB 연결 검증
2. KIS API 토큰 발급/복원
3. 크롤링 엔진 초기화
4. Claude 클라이언트 초기화
5. 안전장치 모듈 초기화
6. 기술적 지표 모듈 초기화
7. 전략 엔진 초기화
8. 리스크 관리 모듈 초기화
9. FastAPI 서버 시작 (백그라운드, 포트 9500)
10. Telegram 양방향 봇 시작
11. 메인 매매 루프 진입

### API 서버만 단독 실행

매매 루프 없이 API 서버만 실행하여 대시보드 개발/테스트를 할 수 있다.

```bash
uvicorn src.monitoring.api_server:app --host 0.0.0.0 --port 9500 --reload
```

### 동작 확인

```bash
# 헬스체크
curl http://localhost:9500/health

# 시스템 상태
curl http://localhost:9500/system/status

# 유니버스 목록
curl http://localhost:9500/universe
```

---

## 12. Flutter 대시보드 설치

### 의존성 설치

```bash
cd dashboard
flutter pub get
```

### macOS 앱 실행

```bash
flutter run -d macos
```

### 빌드 (릴리즈)

```bash
flutter build macos --release
```

빌드된 앱은 `dashboard/build/macos/Build/Products/Release/` 경로에 생성된다.

### 대시보드 연결 설정

대시보드는 기본적으로 `http://localhost:9500`의 API 서버에 연결한다. 다른 호스트/포트를 사용하는 경우 대시보드 설정에서 변경할 수 있다.

---

## 13. LaunchAgent 자동화 설정

macOS LaunchAgent를 사용하여 매일 23:00 KST에 자동으로 시스템을 시작하고, 06:30 KST에 종료한다.

### 설치

```bash
cd scripts
chmod +x install_launchagent.sh auto_trading.sh
./install_launchagent.sh install
```

### 관리 명령어

```bash
# 상태 확인
./install_launchagent.sh status

# 수동 시작
./install_launchagent.sh start

# 수동 종료
./install_launchagent.sh stop

# 제거
./install_launchagent.sh uninstall
```

### 자동 매매 스크립트 기능

`scripts/auto_trading.sh`가 수행하는 작업:

1. 네트워크 연결 확인 (최대 5분 대기)
2. Docker Desktop 시작 및 헬스체크
3. Python 가상환경 활성화
4. 포트 9500 충돌 정리
5. 트레이딩 시스템 시작
6. 프로세스 감시 (비정상 종료 시 자동 재시작, 최대 10회)
7. 06:30 KST 종료 시간 도달 시 안전 종료

### 로그 위치

```
~/Library/Logs/trading/
├── auto_trading.log        # LaunchAgent 실행 로그
├── trading_stdout.log      # 시스템 표준 출력
├── trading_stderr.log      # 시스템 오류 출력
└── trading.pid             # 프로세스 ID
```

---

## 14. 문제 해결

### Docker 관련

**포트 충돌**
```bash
# 5432 또는 6379 포트가 사용 중인 경우
lsof -i :5432
# .env에서 DB_PORT 또는 REDIS_PORT를 변경한다
```

**컨테이너가 시작되지 않는 경우**
```bash
docker compose logs postgres
docker compose logs redis
# 볼륨 초기화 후 재시작
docker compose down -v && docker compose up -d
```

### KIS API 관련

**OPSQ2000 에러**
계좌번호가 올바른지 확인한다. `KIS_VIRTUAL_ACCOUNT`와 `KIS_REAL_ACCOUNT`의 형식이 `XXXXXXXX-XX`인지 검증한다.

**토큰 만료**
토큰은 24시간 유효하다. 시스템이 자동으로 갱신하지만, 수동으로 초기화해야 하는 경우:
```bash
rm data/kis_token.json data/kis_real_token.json
```

**시세 조회 실패 (모의투자 모드)**
모의투자 서버에는 시세 API가 없다. `KIS_REAL_APP_KEY`와 `KIS_REAL_APP_SECRET`이 설정되어 있는지 확인한다.

### Python 관련

**ModuleNotFoundError**
```bash
source .venv/bin/activate  # 가상환경 활성화 확인
pip install -r requirements.txt
```

**MLX 관련 오류 (Intel Mac)**
MLX는 Apple Silicon 전용이다. Intel Mac에서는 `MLX_ENABLED=0`으로 설정한다.

### Claude CLI 관련

**중첩 세션 오류**
`CLAUDECODE` 환경변수가 설정되어 있으면 제거한다:
```bash
unset CLAUDECODE
unset CLAUDE_CODE
```

**인증 실패**
```bash
claude auth login  # 재인증
```

### API 서버 관련

**포트 9500 사용 중**
```bash
lsof -ti :9500 | xargs kill -9
```

### 일반적인 확인 사항

```bash
# Python 버전 확인
python3 --version

# Docker 상태 확인
docker compose ps

# DB 연결 확인
docker exec -it trading-postgres pg_isready -U trading

# Redis 연결 확인
docker exec -it trading-redis redis-cli -a ${REDIS_PASSWORD} ping
```
