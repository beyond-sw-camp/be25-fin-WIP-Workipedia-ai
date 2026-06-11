# Workipedia AI Architecture Overview

> 상태: Draft  
> 최종 수정: 2026-06-11

## 핵심 원칙

- 지식 제공은 RAG로 통일한다.
- QLoRA와 LangGraph는 사용하지 않는다.
- 고객사별로 별도 배포하고 로컬/클라우드 차이는 provider 추상화와 배포 설정으로 처리한다.
- 민감정보는 저장과 모델 호출 전에 마스킹한다.
- 구조화된 실시간 데이터는 Tool Integration으로 조회한다.

## 폴백 파이프라인

폴백 순서: A 매뉴얼 → B 워키 → C 지식 RAG → D Tool Calling

```text
A. 매뉴얼 RAG
→ 실패
B. 워키 RAG
→ 실패
C. 지식 RAG
   - TEAM_ADMIN 승인 지식화 게시판(`KNOWLEDGE_DATA`)
   - SYSTEM_ADMIN 수기 지식(`MANUAL_KNOWLEDGE`)
→ 실패
D. 등록된 Tool 호출
→ 실패
요청 티켓 생성 전환 액션
```

- 해결된 티켓 이력은 별도 단계가 아니며 TEAM_ADMIN 승인 지식화 게시판(C)으로만 반영한다.
- `knowledge_data`와 `manual_knowledge`는 DB·`sourceType`·collection을 분리한다.
- C단계는 두 collection을 독립 조회한 뒤 후보를 합쳐 통합 reranking한다.
- 각 단계는 구조화된 실행 상태에 따라 다음 단계로 이동한다.

구현은 LangGraph 대신 명시적인 Python for-loop와 if-else를 사용한다.

```python
for route in route_order:
    result = execute(route, request)
    if result.is_success:
        return result

return create_transition_action(request)
```

각 단계는 자유 텍스트가 아니라 공통 실행 상태를 반환한다.

```text
SUCCESS   : 유효한 근거 또는 Tool 결과로 답변 완료
NO_RESULT : 근거 부족으로 다음 단계 진행
ERROR     : timeout 등 실행 실패로 다음 단계 진행
BLOCKED   : 보안 또는 입력 검증 실패로 즉시 안전 응답
```

Reranker는 정렬 결과만 반환하지 않고 각 후보의 `candidate_id`, 원본 `score`, `rank`를 함께 반환한다. 라우팅 판단에서는 이를 바탕으로 `top_score`와 `score_margin`을 계산한다.

LLM 응답 문자열에서 특정 문구를 찾는 방식은 보조 수단으로도 사용하지 않는다.

### RAG Negative Answer 판정

다음 조건 중 하나면 `NO_RESULT`로 처리한다.

- 검색된 chunk가 없음
- Cross-Encoder 최고 점수가 설정 임계값 미만
- 유효한 출처가 하나도 없음
- 생성된 답변의 인용 ID가 검색 결과와 일치하지 않음
- 구조화된 생성 결과가 `INSUFFICIENT_CONTEXT`를 반환

민감정보 마스킹 실패나 허용되지 않은 Tool 입력은 `BLOCKED`로 처리하며 다음 경로로 넘기지 않는다.

## 주요 컴포넌트

```text
API Layer
└─ Orchestrator
   ├─ SensitiveDataMasker
   ├─ ManualRetriever
   ├─ WorkiRetriever
   ├─ KnowledgeRetriever
   │  ├─ KnowledgeDataRetriever
   │  └─ ManualKnowledgeRetriever
   ├─ ManualKnowledgeIndexer
   ├─ ToolSelector
   ├─ DepartmentRoutingService
   ├─ CrossEncoderReranker
   ├─ LlmProvider
   └─ EmbeddingProvider
```

## Provider 추상화

```text
LlmProvider
├─ LocalLlmProvider
└─ CloudLlmProvider

EmbeddingProvider
├─ LocalEmbeddingProvider
└─ CloudEmbeddingProvider
```

모든 구현체는 동일한 요청/응답 계약, timeout, 오류 타입을 제공해야 한다.

## 레포 책임

### AI

- 문서 chunking, embedding, retrieval
- 수기 지식 chunking과 Vector Store 동기화
- 매뉴얼, 워키, 수기 지식, 승인된 지식화 문서, 승인된 라우팅 사례의 chunking
- 출처 기반 답변 생성
- Tool 선택, 결과 마스킹과 해석
- 폴백 오케스트레이션
- 관리자 작성 부서 R&R과 승인된 처리 사례 기반 후보 검색
- Cross-Encoder 기반 문서 및 부서 후보 reranking
- 처리 완료·승인 티켓 사례의 Vector Store 동기화
- 민감정보 탐지/마스킹

### BE

- 인증과 사용자 권한
- API Tool 정의와 인증정보 관리
- 개발자용 DB Query Tool 템플릿, 검증 및 승인 상태 관리
- Tool HTTP/DB 실행
- 수기 지식 CRUD와 동기화 상태 저장
- 티켓과 관리자 설정 저장
- 이미지 저장소 S3/MinIO 추상화
- 감사 로그
