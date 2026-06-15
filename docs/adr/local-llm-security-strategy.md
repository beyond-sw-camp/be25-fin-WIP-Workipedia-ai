# ADR 008 - Customer-specific LLM and Data Security Strategy

> 문서 유형: ADR
> 상태: Accepted
> 정본 위치: `docs/adr/local-llm-security-strategy.md`
> 관련 문서: `docs/adr/deployment-and-data-security.md`, `docs/adr/rag-strategy.md`, `docs/domain-guides/chatbot-rag.md`
> 버전: v0.3
> 최종 수정: 2026-06-12

## Context

Workipedia는 사내 문서, 워키 지식, 요청 티켓을 활용해 답변을 생성한다.
이 데이터에는 회사 내부 규정, 업무 절차, 사용자 질문, 티켓 내용이 포함된다.

고객사마다 보안 정책과 인프라 조건이 다르므로 하나의 모델 배포 방식을 강제할 수 없다.

## Decision

고객사 설정에 따라 LLM과 Embedding provider를 선택한다.

기본 원칙:

- LLM provider는 `local`, `openai`, `google`, `anthropic`, `fallback`을 지원한다.
- Embedding provider는 `ollama`, `openai`, `google`을 지원한다.
- `fallback` LLM은 OpenAI → Google → Anthropic 순서로 다음 provider를 시도한다.
- 애플리케이션 코드는 `LlmProvider`, `EmbeddingProvider` 인터페이스에 의존한다.
- BE RDB는 암호화 저장하며 읽을 때만 복호화한다.
- AI 서버는 사용자에게 반환하는 LLM 응답에만 마스킹을 적용한다. LLM 입력과 Vector Store 저장은 원문을 사용한다.
- 챗봇 답변은 반드시 매뉴얼/워키 출처를 포함한다.
- 근거가 부족하면 답변을 생성하지 않고 요청 티켓 전환을 안내한다.

## Consequences

- 고객사별 배포 조건을 provider 설정으로 흡수하여 핵심 RAG 코드를 공유할 수 있다.
- 클라우드 provider를 사용하더라도 LLM 입력은 원문이며, 응답만 마스킹하여 사용자에게 전달한다.
- 모델 성능보다 개인정보 보호, 출처 추적, 실패 전환이 우선된다.
- provider별 설정, 장애 처리, 품질 평가가 중요해진다.

## Confirmed Decisions

- 고객사마다 별도 배포하고 환경변수 또는 배포 프로파일로 provider를 선택한다.
- 하나의 서버에서 tenant별 provider를 런타임 전환하지 않는다.
- 주민등록번호와 카드번호는 LLM 응답에서 항상 마스킹한다.
- 전화번호와 이메일은 설정에 따라 선택적으로 마스킹한다.
- 계좌번호는 오탐 정책이 확정되지 않아 아직 구현하지 않는다.
