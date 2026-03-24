# Guardian Requirements Log -- Session 7 (환율 폴백 + 포트 변경)

## User Original Requirements (전문)

"환율 조회 실패, 폴백 사용: 1350 여기서 폴백은 '조회불가'로 하고, 중간중간 로직을 KIS키 조회 -> 구글 -> 네이버 -> 등등 순서로 크롤링하는 방식으로 10가지 안전장치 마련해줘. 그리고 앱 설치시 항상 서버는 9501~9505 포트를 사용해서 다른것들과 충돌 안나도록 할꺼야."

## Current Phase: Implementation
## Phase Goal: 환율 폴백 변경 + 10단계 환율 조회 소스 구현 + 포트 범위 변경 (9500 제거, 9501~9505만 허용)
## Active Agents: general-purpose agents (순차)

## Critical Requirements (즉시 개입 필요)
- [CRITICAL] 환율 조회 최종 폴백을 1350.0 → "조회불가"로 변경 (모든 파일에서)
- [CRITICAL] 환율 조회 소스를 10개로 확대 (KIS → Google → Naver → 등 순서)
- [CRITICAL] 서버 포트를 9501~9505로 변경 (9500 제외, 타 서비스 충돌 방지)
- [CRITICAL] Korean comments 유지
- [CRITICAL] SRP 준수, 파일 200줄 이내
- [CRITICAL] 워크어라운드 사용 금지

## Standard Requirements (Phase 완료 전 검증)
- 기존 기능 호환성 유지 (세금 계산 등에서 1350.0을 사용하는 코드가 "조회불가"와 호환되어야 함)
- 환율 조회 실패 시 UI에 "조회불가" 명확히 표시
- 포트 변경이 모든 관련 파일에 일관 적용 (Python, Dart, Shell, Docker, 문서)
