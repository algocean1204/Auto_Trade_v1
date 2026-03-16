# MLXClassifier

## 역할
Apple Silicon MPS에서 Qwen3-30B-A3B MoE 모델을 MLX로 로컬 실행하여 뉴스 기사를 분류한다. Claude API 비용 절감을 위한 로컬 대체 분류기로, 모델 로드 실패 시 NewsClassifier(Claude API)로 graceful fallback한다.

## 소속팀
분석팀 (Analysis Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| MODEL_NAME | mlx-community/Qwen3-30B-A3B-4bit | HuggingFace 모델 ID (4bit 양자화) |
| MIN_CONFIDENCE | 0.90 | 최소 신뢰도 임계값 (이하면 Claude API fallback) |
| 유효 관련성 | high/medium/low | relevance 분류 값 |
| 유효 감성 | bullish/bearish/neutral | sentiment 분류 값 |
| 유효 영향도 | high/medium/low | impact 분류 값 |
| 실행 환경 | Apple Silicon MPS | macOS 전용 (Docker 불가) |

## 동작 흐름
1. `mlx_lm` 패키지 임포트 시도 (Apple Silicon 전용)
2. 모델 로드 실패 시 `MLXClassifier` 비활성화, Claude API fallback
3. 기사 텍스트에 시스템 프롬프트 + 사용자 프롬프트 조합
4. MLX 추론 실행 (로컬 MPS 가속)
5. JSON 블록 파싱 (`\`\`\`json ... \`\`\`` 패턴 추출)
6. 신뢰도 `MIN_CONFIDENCE` 미만이면 None 반환 (caller가 Claude로 재처리)
7. 분류 결과 반환

## 입력
- 기사 텍스트 (title + content 결합)

## 출력
- `relevance`: high/medium/low
- `sentiment`: bullish/bearish/neutral
- `impact`: high/medium/low
- `confidence`: 0.0~1.0
- `summary`: 시장 영향 요약 (1~2문장)
- `tickers_affected`: 영향받는 종목 리스트

## 의존성
- `mlx_lm`: Apple Silicon MPS 추론 라이브러리 (선택적)
- `mlx-community/Qwen3-30B-A3B-4bit`: HuggingFace 모델
- `NewsClassifier`: fallback 분류기

## 소스 파일
`src/common/local_llm.py`

## 상태
- 활성: ✅ (mlx-lm 설치 시)
- 마지막 실행: (자동 업데이트)
