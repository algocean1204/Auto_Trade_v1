# KnowledgeManager

## 역할
금융 뉴스 분류 중 미지 용어를 자동 감지하여 Claude Opus로 정의를 획득하고, ChromaDB에 영구 저장하는 RAG 지식 베이스 관리자다. bge-m3 임베딩 기반 벡터 검색으로 관련 지식을 실시간 조회한다.

## 소속팀
분석팀 (Analysis Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| ChromaDB 경로 | data/chroma | 로컬 영속 스토리지 |
| 지식 디렉토리 | knowledge/ | 초기 지식 문서 디렉토리 |
| 임베딩 모델 | bge-m3 | 다국어 벡터 임베딩 |
| 미지 용어 패턴 | 대문자 약어/하이픈 용어/PascalCase | 금융 용어 자동 감지 정규식 |
| Claude 모델 | Opus | 용어 정의 생성 (1회 호출) |
| 일반 약어 제외 | THE, AND, API, URL 등 | 불필요한 학습 방지 목록 |

## 동작 흐름
1. 기사 텍스트에서 `_TERM_PATTERN` 정규식으로 용어 후보 추출
2. `_COMMON_ABBREVIATIONS`에 있는 일반 단어 제외
3. ChromaDB에 이미 저장된 용어인지 조회
4. 미지 용어면 Claude Opus에 정의 요청 (`_TERM_DEFINITION_PROMPT`)
5. 반환된 JSON(term, definition, category, related_terms) 파싱
6. bge-m3로 임베딩 생성
7. ChromaDB에 영구 저장
8. 이후 검색 시 벡터 유사도 기반 조회 제공

## 입력
- 금융 뉴스 기사 텍스트 (분류 파이프라인에서 전달)

## 출력
- 감지된 미지 용어 목록
- 용어별 정의 (definition, category, related_terms)
- 벡터 검색 결과 (관련 용어 + 정의)

## 의존성
- `chromadb`: 로컬 벡터 DB (선택적 의존성)
- `BGEEmbedder (bge-m3)`: 임베딩 생성
- `ClaudeClient`: 용어 정의 생성 (Opus)
- `knowledge/`: 초기 지식 문서 파일

## 소스 파일
`src/optimization/rag/knowledge_manager.py`

## 상태
- 활성: ✅ (chromadb 설치 시)
- 마지막 실행: (자동 업데이트)
