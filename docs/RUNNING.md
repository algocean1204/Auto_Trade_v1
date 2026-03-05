# AI Auto-Trading System V2 - 실행 가이드

## 사전 요구사항

### 환경

- macOS (Apple Silicon M4 Pro 권장)
- Python 3.11+
- Docker Desktop
- 48GB RAM (권장, MLX 로컬 AI 사용 시)

### 필수 API 키

- **KIS (한국투자증권)**: 실전/모의 앱 키, 앱 시크릿, 계좌번호
- **Claude AI**: Anthropic API 키 또는 Claude Code MAX CLI

### 선택 API 키 (크롤링 품질 향상)

- Finnhub, AlphaVantage, FRED (경제 데이터)
- Reddit API (WSB, investing 크롤링)
- Telegram Bot (알림)

## 설치 및 설정

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집하여 API 키를 입력한다. 필요한 변수 목록은 [DEPLOYMENT.md](DEPLOYMENT.md)를 참조한다.

### 2. Docker 서비스 시작

PostgreSQL과 Redis를 Docker로 실행한다.

```bash
# 개발 환경 시작
docker compose --profile dev up -d

# 상태 확인
docker compose --profile dev ps
```

정상 상태 확인:
```
trading-postgres   pgvector/pgvector:pg17   ... (healthy)
trading-redis      redis:7-alpine           ... (healthy)
```

### 3. Python 가상환경 및 의존성 설치

```bash
# 가상환경 생성
python3 -m venv .venv

# 가상환경 활성화
source .venv/bin/activate

# 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. BGE 임베딩 모델 다운로드 (RAG용)

RAG 시스템에서 사용하는 BGE-M3 임베딩 모델을 다운로드한다.

```bash
python3 scripts/download_fallback_model.py
```

## 실행 방법

### 방법 1: 스크립트 사용 (권장)

```bash
./scripts/run_trading_system.sh
```

이 스크립트는 다음을 자동으로 수행한다:
- 가상환경 활성화
- Docker 컨테이너 상태 확인 및 시작
- 의존성 자동 설치
- 시스템 실행

### 방법 2: 직접 실행

```bash
# 가상환경 활성화
source .venv/bin/activate

# Docker 서비스 확인
docker compose --profile dev up -d

# 시스템 실행
python3 -m src.main
```

### 방법 3: LaunchAgent 자동 실행 (야간 매매)

```bash
# LaunchAgent 설치 (매일 23:00 KST 자동 시작)
./scripts/install_launchagent.sh install

# 상태 확인
./scripts/install_launchagent.sh status
```

## Flutter 대시보드 실행

별도 터미널에서 실행한다.

```bash
cd dashboard
flutter pub get
flutter run -d macos
```

API 서버(localhost:9500)가 실행 중이어야 대시보드가 정상 작동한다.

## 시스템 동작 확인

### 1. API 서버 확인

```bash
# 시스템 상태
curl http://localhost:9500/system/status

# API 문서 (Swagger UI)
open http://localhost:9500/docs
```

### 2. 로그 확인

```bash
# 실시간 로그 (LaunchAgent 실행 시)
tail -f ~/Library/Logs/trading/trading_stdout.log

# 에러 로그
tail -f ~/Library/Logs/trading/trading_stderr.log
```

### 3. 데이터베이스 확인

```bash
# PostgreSQL 접속
docker compose exec postgres psql -U trading -d trading_system

# 주요 테이블 확인
SELECT count(*) FROM articles;        -- 크롤링 기사 수
SELECT count(*) FROM trades;          -- 거래 수
SELECT * FROM etf_universe;           -- ETF 유니버스
SELECT * FROM fear_greed_history ORDER BY date DESC LIMIT 5;  -- F&G 이력
```

## 실행 흐름

### Pre-market 준비 단계 (23:00 KST)

1. **Infrastructure Check** (23:00~23:05)
   - Docker, DB, Redis 상태 확인
   - KIS API 토큰 갱신
   - 보유 포지션 확인

2. **Full Crawling** (23:05~23:25)
   - 30개 소스에서 병렬 크롤링
   - Redis 중복 제거
   - 룰 기반 필터링

3. **Crawl Verification** (23:25~23:28)
   - Claude Sonnet으로 크롤링 품질 검증

4. **Classification** (23:28~23:48)
   - Claude Sonnet 배치 호출로 뉴스 분류
   - 카테고리, 영향도, 방향 판정

5. **Market Analysis** (23:48~23:55)
   - Claude Opus로 시장 레짐 감지
   - VIX 기반 전략 결정

6. **Safety Check** (23:55~23:59)
   - API 할당량, Claude ping, KIS 최종 점검

### Regular Market 거래 루프 (00:00 or 22:30/23:30 KST)

**15분 주기로 반복:**

1. Delta Crawl (새 뉴스만 빠르게 수집)
2. Classify (새 뉴스 분류)
3. Decide (Claude Opus로 매매 결정)
4. Execute (KIS API 주문 실행)
5. Monitor (포지션 모니터링, 손절/익절 체크)

### EOD 정리 단계 (장 마감 후)

1. Overnight Judgment - 보유 포지션 overnight 판단
2. Daily Feedback - Claude Opus로 당일 매매 분석
3. Forced Liquidation - 3일 이상 보유 포지션 강제 청산
4. Cleanup - 일일 카운터 리셋

### Weekly Analysis (일요일)

- 주간 성과 심층 분석
- 파라미터 조정 제안
- 사용자 승인 대기

## 종료

### Graceful Shutdown

Ctrl+C를 누르면 시스템이 안전하게 종료된다:
1. 진행 중 매매 루프 완료 대기
2. API 서버 종료
3. DB 연결 종료
4. Redis 연결 종료
5. 모든 비동기 태스크 취소

### Docker 서비스 종료

```bash
# 컨테이너만 종료 (데이터 보존)
docker compose --profile dev down

# 데이터까지 삭제 (주의)
docker compose --profile dev down -v
```

## 모의투자 vs 실전투자

### 모의투자 (권장 시작점)

`.env` 설정:
```
KIS_MODE=virtual
TRADING_MODE=paper
```

- 실제 돈을 사용하지 않는다
- 모든 기능을 테스트할 수 있다
- 최소 1주일 이상 검증 후 실전 전환한다

### 실전투자

`.env` 설정:
```
KIS_MODE=real
TRADING_MODE=live
```

**주의사항:**
- 작은 금액으로 시작한다
- 손실 한도 파라미터를 엄격히 설정한다
- 텔레그램 알림을 반드시 설정한다
- 긴급 정지 방법을 숙지한다

## 트러블슈팅

### 1. KIS API 토큰 오류

**증상:** "KIS API check failed" 또는 "INPUT INVALID_CHECK_ACNO"

**해결:**
- `.env`의 KIS 자격증명을 확인한다
- `data/kis_token.json`, `data/kis_real_token.json`을 삭제하고 재시작한다
- KIS Developers 사이트에서 앱 키 상태를 확인한다
- "INPUT INVALID_CHECK_ACNO"는 KIS 서버 간헐적 오류이므로 자동 재시도된다

### 2. DB 연결 실패

**증상:** "DB check failed"

**해결:**
```bash
# Docker 컨테이너 재시작
docker compose --profile dev restart postgres

# 연결 확인
docker compose exec postgres psql -U trading -d trading_system -c "SELECT 1;"
```

### 3. Redis 연결 실패

**증상:** "Redis check failed"

**해결:**
```bash
docker compose --profile dev restart redis
```

### 4. Claude API Quota 초과

**증상:** QuotaGuard 경고

**해결:**
- Anthropic 대시보드에서 크레딧 확인
- `CLAUDE_MODE=local`로 로컬 MLX 폴백 사용
- `TRADING_MODE=paper`로 API 호출 최소화

### 5. 크롤링 실패

**증상:** "Crawl complete: saved=0"

**해결:**
- 인터넷 연결을 확인한다
- 선택 API 키를 추가한다 (Finnhub, AlphaVantage)
- `curl http://localhost:9500/crawl/status/{task_id}`로 상태를 확인한다

### 6. yfinance 야간 데이터 오류

**증상:** VIX가 0.0으로 반환

**해결:**
- 야간에 yfinance가 불안정할 수 있다
- VIX 0.0 반환 시 자동으로 20.0으로 폴백한다
- FRED API 키를 설정하면 FRED에서 VIX를 가져온다

### 7. Claude CLI 중첩 세션 오류

**증상:** "CLAUDECODE env var" 관련 오류

**해결:**
- `auto_trading.sh`에서 자동으로 `CLAUDECODE` 환경변수를 제거한다
- 수동 실행 시: `unset CLAUDECODE && python3 -m src.main`

## 데이터 백업

### PostgreSQL

```bash
# 백업
docker compose exec postgres pg_dump -U trading trading_system > backup_$(date +%Y%m%d).sql

# 복원
docker compose exec -T postgres psql -U trading trading_system < backup_20260219.sql
```

### 설정 파일

```bash
cp strategy_params.json strategy_params_backup_$(date +%Y%m%d).json
cp data/trading_principles.json data/trading_principles_backup_$(date +%Y%m%d).json
```
