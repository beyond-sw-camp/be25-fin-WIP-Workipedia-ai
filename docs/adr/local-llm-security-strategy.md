# ADR 008 - Customer-specific LLM and Data Security Strategy

> 문서 유형: ADR
> 상태: Accepted
> 정본 위치: `docs/adr/local-llm-security-strategy.md`
> 관련 문서: `docs/adr/deployment-and-data-security.md`, `docs/adr/rag-strategy.md`, `docs/domain-guides/chatbot-rag.md`
> 버전: v0.2
> 최종 수정: 2026-06-09

## Context

Workipedia는 사내 문서, 워키 지식, 요청 티켓을 활용해 답변을 생성한다.
이 데이터에는 회사 내부 규정, 업무 절차, 사용자 질문, 티켓 내용이 포함된다.

고객사마다 보안 정책과 인프라 조건이 다르므로 하나의 모델 배포 방식을 강제할 수 없다.

## Decision

고객사 설정에 따라 로컬 또는 클라우드 LLM/Embedding provider를 선택한다.

기본 원칙:

- A사처럼 내부망 운영이 필요한 고객은 로컬 provider를 사용한다.
- B사처럼 클라우드 사용이 가능한 고객은 외부 API provider를 사용할 수 있다.
- 애플리케이션 코드는 `LlmProvider`, `EmbeddingProvider` 인터페이스에 의존한다.
- 사용자의 질문, 티켓, 문서에서 민감정보를 탐지하면 저장 및 모델 호출 전에 마스킹한다.
- 마스킹 전 원문은 기본적으로 DB에 보관하지 않는다.
- 챗봇 답변은 반드시 매뉴얼/워키 출처를 포함한다.
- 근거가 부족하면 답변을 생성하지 않고 요청 티켓 전환을 안내한다.

## Consequences

- 고객사별 배포 조건을 provider 설정으로 흡수하여 핵심 RAG 코드를 공유할 수 있다.
- 클라우드 provider 사용 시에도 마스킹된 데이터만 전송한다.
- 모델 성능보다 개인정보 보호, 출처 추적, 실패 전환이 우선된다.
- provider별 설정, 장애 처리, 품질 평가가 중요해진다.

## Confirmed Decisions

- 고객사마다 별도 배포하고 환경변수 또는 배포 프로파일로 provider를 선택한다.
- 하나의 서버에서 tenant별 provider를 런타임 전환하지 않는다.
- 마스킹 전 원문은 DB와 로그에 보관하지 않는다.
- 주민등록번호, 계좌번호, 연락처 등 민감정보 유형별 탐지·치환 규칙을 운영 설정으로 관리한다.
