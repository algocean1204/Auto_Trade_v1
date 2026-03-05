# 🤖 AI 자동매매 시스템 V2

미국 2X 레버리지 ETF(SOXL, QLD, TQQQ 등) 자동매매 시스템이다.
Claude AI + 로컬 LLM 앙상블로 뉴스 분석 → 매매 판단 → 주문 실행 → 피드백 학습까지 전 과정을 자동화한다.

## 📊 시스템 개요

| 항목 | 내용 |
|------|------|
| 매매 대상 | 미국 2X 레버리지 ETF 12종 (SOXL, QLD, SSO 등) |
| 브로커 | 한국투자증권 KIS OpenAPI |
| AI 분석 | Claude Opus/Sonnet/Haiku + 로컬 GGUF 모델 4종 |
| 뉴스 크롤링 | 30개 소스 실시간 수집 |
| 대시보드 | Flutter 데스크톱 앱 (macOS) |
| DB | PostgreSQL 17 + pgvector + Redis 7 |
| 스케줄링 | macOS LaunchAgent (매일 23:00~06:30 KST) |

## 🧠 AI 모델 구성

### Claude API (Anthropic)

이 프로젝트는 [Claude Code](https://claude.ai/claude-code) 구독이 필요하다.
Claude Code SDK를 통해 로컬에서 Claude API를 호출하며, API 키 없이도 SDK 모드로 동작한다.

| 모델 | 용도 | 비고 |
|------|------|------|
| **Claude Opus 4.6** (`claude-opus-4-6`) | 프리미엄 분석 (고난도 추론) | SDK/API 모드 선택 가능 |
| **Claude Sonnet 4.6** (`claude-sonnet-4-6`) | 종합 분석, 상황 추적, EOD 피드백 | 메인 분석 엔진 |
| **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) | 뉴스 분류 정밀화 | 빠른 분류 보정 |

> **Claude Code 구독**: https://claude.ai/claude-code
> SDK 모드(`CLAUDE_MODE=local`)를 사용하면 별도 API 키 없이 Claude Code 구독만으로 동작한다.

### 로컬 GGUF 모델 (Apple Silicon MLX/Metal)

뉴스 분류와 번역을 위해 4개 로컬 모델을 사용한다.
3개 모델의 다수결 투표(Majority Vote)로 분류 신뢰도를 높인다.

| 모델 | 양자화 | 용도 | HuggingFace |
|------|--------|------|-------------|
| **Qwen2.5-7B-Instruct** | Q4_K_M (~5GB) | 뉴스 분류 (카테고리/방향/임팩트) | [Qwen/Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) |
| **Meta-Llama-3.1-8B-Instruct** | Q4_K_M (~5GB) | 앙상블 합의 투표 | [meta-llama/Meta-Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3.1-8B-Instruct) |
| **DeepSeek-R1-Distill-Llama-8B** | Q4_K_M (~5GB) | 추론 기반 최종 분류 | [deepseek-ai/DeepSeek-R1-Distill-Llama-8B](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-8B) |
| **Llama-3-Korean-Bllossom-8B** | Q8_0 (~7GB) | 영→한 뉴스 제목 번역 | [nlpai-lab/Bllossom-ko-8B](https://huggingface.co/nlpai-lab/Bllossom-ko-8B) |

> GGUF 파일을 `models/` 디렉토리에 다운로드해야 한다. 총 ~22GB GPU 메모리가 필요하다.

### 임베딩 & RAG

| 모델 | 용도 | HuggingFace |
|------|------|-------------|
| **BAAI/bge-m3** | 다국어 벡터 임베딩 (RAG 검색) | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) |

ChromaDB에 매매 패턴을 저장하고, 유사 패턴을 검색하여 전략 최적화에 활용한다.

### ML 최적화

| 라이브러리 | 용도 |
|------------|------|
| **LightGBM** | 진입 신호 이진 분류 모델 |
| **Optuna** | 하이퍼파라미터 최적화 (200 trials, TPE) |
| **scikit-learn** | Walk-Forward 교차검증 (TimeSeriesSplit) |

## ⚙️ 설치 및 설정

### 필수 요구 사항

- **macOS** (Apple Silicon M1 이상 권장, Metal GPU 필요)
- **Python 3.12+**
- **Flutter 3.x** (대시보드 빌드용)
- **Docker & Docker Compose** (PostgreSQL, Redis)
- **Claude Code 구독** (SDK 모드) 또는 Anthropic API 키

### 1. 저장소 클론 및 환경 설정

```bash
git clone https://github.com/algocean1204/Auto_Trade_v1.git
cd Auto_Trade_v1

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집하여 아래 항목을 설정한다:

| 변수 | 설명 | 필수 |
|------|------|------|
| `KIS_REAL_APP_KEY` | 한국투자증권 실전 앱 키 | ✅ |
| `KIS_REAL_APP_SECRET` | 한국투자증권 실전 앱 시크릿 | ✅ |
| `KIS_REAL_ACCOUNT_NO` | 실전 계좌번호 (8자리-2자리) | ✅ |
| `KIS_VIRTUAL_APP_KEY` | 모의투자 앱 키 | 모의투자 시 |
| `KIS_VIRTUAL_APP_SECRET` | 모의투자 앱 시크릿 | 모의투자 시 |
| `KIS_VIRTUAL_ACCOUNT_NO` | 모의투자 계좌번호 | 모의투자 시 |
| `CLAUDE_MODE` | Claude 실행 모드 (`local`/`api`/`hybrid`) | ✅ |
| `ANTHROPIC_API_KEY` | Anthropic API 키 (`api` 모드 시) | `api` 모드만 |
| `FINNHUB_API_KEY` | Finnhub 뉴스 API 키 | ✅ |
| `ALPHAVANTAGE_API_KEY` | AlphaVantage 시장 데이터 API 키 | ✅ |
| `FRED_API_KEY` | FRED 경제지표 API 키 | ✅ |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 알림 봇 토큰 | 선택 |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID | 선택 |
| `DB_PASSWORD` | PostgreSQL 비밀번호 | ✅ |
| `REDIS_PASSWORD` | Redis 비밀번호 | ✅ |
| `API_SECRET_KEY` | 대시보드 API 인증 키 | ✅ |

### 3. 인프라 실행

```bash
# PostgreSQL + Redis 컨테이너 실행
docker compose up -d

# DB 마이그레이션
alembic upgrade head
```

### 4. GGUF 모델 다운로드

`models/` 디렉토리에 아래 GGUF 파일을 다운로드한다:

```
models/
├── Qwen2.5-7B-Instruct-Q4_K_M.gguf
├── Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf
├── DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf
└── llama-3-Korean-Bllossom-8B.Q8_0.gguf
```

> HuggingFace에서 GGUF 양자화 버전을 검색하여 다운로드한다.

### 5. 대시보드 빌드

```bash
cd dashboard
flutter pub get
flutter run -d macos
```

### 6. 시스템 실행

```bash
# 매매 루프 포함 전체 시스템 실행
python src/main.py

# 대시보드만 실행 (매매 루프 없이 API 서버만)
python scripts/start_dashboard.py
```

## 🏗️ 아키텍처

```
src/
├── main.py                     # 시스템 진입점
├── common/                     # 공통 모듈 (로깅, 시크릿, AI 게이트웨이)
├── analysis/                   # AI 분석 (Claude 팀, 뉴스 분류, 레짐 판별)
├── crawlers/                   # 뉴스 크롤러 (30개 소스)
├── executor/                   # 주문 실행 (KIS API 브로커)
├── indicators/                 # 기술 지표 (RSI, MACD, BB, 볼륨프로파일, 고래추적)
├── monitoring/                 # FastAPI 서버 (112개 엔드포인트, 27개 라우터)
├── optimization/               # ML 최적화 (LightGBM, Optuna, RAG)
├── orchestration/              # 오케스트레이션 (DI, 매매루프, EOD 시퀀스)
├── risk/                       # 리스크 관리 (게이트, 마찰비용, 하우스머니)
├── safety/                     # 안전 장치 (비상 프로토콜, 데드맨 스위치)
├── scalping/                   # 스캘핑 (유동성 분석, 스푸핑 탐지)
├── strategy/                   # 전략 (진입/청산, 비스트모드, 통계차익)
├── tax/                        # 세금/수수료 추적
├── telegram/                   # 텔레그램 봇
└── websocket/                  # KIS 실시간 WebSocket

dashboard/                      # Flutter 대시보드 앱
├── lib/
│   ├── models/                 # 데이터 모델
│   ├── providers/              # 상태 관리 (28개 Provider)
│   ├── screens/                # 화면 (15개 스크린)
│   ├── services/               # API/WebSocket 서비스
│   └── widgets/                # 공통 위젯
```

### 핵심 파이프라인

```
뉴스 수집 (30개 소스)
    ↓
로컬 LLM 앙상블 분류 (Qwen + Llama + DeepSeek → 다수결)
    ↓ (임팩트 >= 0.5일 때)
Claude Haiku 정밀 분류
    ↓
Bllossom-8B 한국어 번역
    ↓
Claude Sonnet 상황 추적 & 종합 분석
    ↓
매매 판단 → 주문 실행 (KIS API)
    ↓
EOD 피드백 (Claude Sonnet)
    ↓
RAG 업데이트 (BGE-M3 → ChromaDB)
    ↓
LightGBM 재학습 (Optuna 200 trials)
```

## 📡 API 서버

FastAPI 기반 모니터링 서버가 112개 엔드포인트를 제공한다.

| 카테고리 | 엔드포인트 수 | 설명 |
|----------|--------------|------|
| Dashboard | 9 | 포지션, 수익률, 차트 데이터 |
| Analysis | 3 | 종합 분석, 뉴스 분석 |
| Trading | 3 | 매매 시작/중지/상태 |
| News | 4 | 뉴스 조회/수집 |
| Macro | 7 | 경제지표, VIX, Fear&Greed |
| Universe | 7 | 종목 관리 |
| Principles | 5 | 매매 원칙 CRUD |
| Risk/Safety | 6 | 비상 정지, 안전 상태 |
| 기타 | 68+ | 벤치마크, 전략, 피드백, FX 등 |

## 📝 라이선스

이 프로젝트는 개인 학습 및 연구 목적으로 공개한다.
실제 매매에 사용하여 발생하는 손실에 대해 개발자는 책임지지 않는다.

## ⚠️ 주의 사항

- 이 시스템은 **실제 돈으로 자동매매**를 실행한다. 반드시 모의투자로 충분히 테스트한 후 사용한다.
- KIS OpenAPI 실전 계좌 연동 전 모의투자 계좌로 먼저 검증한다.
- AI 모델의 판단이 항상 정확하지 않다. 손실이 발생할 수 있다.
- API 키 및 비밀번호는 절대 공개하지 않는다. `.env` 파일을 커밋하지 않는다.
- GGUF 모델 파일(~22GB)은 저장소에 포함되지 않는다. 별도 다운로드가 필요하다.
