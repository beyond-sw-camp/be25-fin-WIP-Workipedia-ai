# ADR 002 - RAG Strategy

> 문서 유형: ADR
> 상태: Accepted
> 정본 위치: `docs/adr/rag-strategy.md`
> 관련 문서: `docs/reference/trd.md`, `docs/adr/deployment-and-data-security.md`, `docs/domain-guides/chatbot-rag.md`
> 버전: v0.4
> 최종 수정: 2026-06-12

## Context

발표 일정은 2026-07-03이고, 배포 목표일은 2026-06-26이다. 팀은 완성도 높은 프로젝트를 목표로 하며, 로컬 LLM/임베딩 기반 검색 흐름을 운영 가능한 형태로 구현하고자 한다.

헌법상 챗봇 답변은 출처가 있어야 하며, 근거가 없으면 답변을 꾸며내지 않아야 한다. 따라서 RAG의 핵심은 "멋진 답변 생성"보다 "검색 근거, 출처, 실패 전환, 감사 가능성"이다.

## Decision

AI 지식 전략은 **RAG 중심 아키텍처**로 통일한다.

- 매뉴얼/워키/지식화 문서는 RAG로 검색하고 출처 기반 답변을 생성한다.
- QLoRA와 별도 파인튜닝 파이프라인은 사용하지 않는다.
- 답변 형식, 근거 부족 시 거절, 워키/티켓 전환, 개인정보 처리 규칙은 시스템 프롬프트와 코드 정책으로 제어한다.
- 고객사에 따라 로컬 또는 클라우드 LLM/Embedding provider를 선택하되 RAG 파이프라인의 인터페이스는 유지한다.

### Vector Store

- AI Vector Store는 로컬 Docker 단일 노드 Qdrant를 사용한다.
- MariaDB를 업무 데이터의 정본으로 유지하고 Qdrant는 재색인 가능한 검색 저장소로 취급한다.
- 매뉴얼·워키·승인 지식·수기 지식·티켓 라우팅 사례는 데이터 유형과 수명주기에 따라 collection을 분리한다.
- 각 point에는 `source_type`, `source_id`, `status`, `active` 등 검색과 삭제에 필요한 payload를 저장한다.
- 검색 metric은 cosine similarity를 기본으로 사용한다.
- collection 생성 시 현재 embedding provider의 vector size를 명시하며, vector size가 다른 모델로 변경하면 새 collection을 생성해 재색인한다.
- point ID는 `{source_type}:{source_id}:{chunk_index}`를 기반으로 생성한 deterministic UUID를 사용한다.
- Qdrant의 원본 score는 검색 후보 점수로 보존하고, Cross-Encoder reranking 점수와 혼합하지 않는다.

우선 구현 대상:

- seed 매뉴얼/워키 문서 10~20개 준비
- 기본 로컬 임베딩 모델로 문서 chunk embedding 생성
- 질문 embedding 생성
- top-k 유사 chunk 검색 후 Cross-Encoder reranking
- 검색된 chunk 기반 답변 생성
- 답변에 출처 포함
- `chatbot_messages.references_json` JSON 저장
- 근거 부족 시 워키 질문 또는 요청 티켓 전환 액션 반환
- 개인정보 마스킹 기본 케이스
- 모델 또는 임베딩 실패 시 `ERROR`를 반환하고 다음 운영 폴백 경로로 이동

### 구현 깊이

| 영역 | MVP 기준 | 후순위 |
|---|---|---|
| 임베딩 | 기본 `bge-m3`, 고객사별 provider adapter | 고성능 모델 교체 |
| Vector Store | Qdrant (로컬 persistent) | 고성능 managed vector DB |
| 검색 | vector top-k + Cross-Encoder reranking | hybrid search, 평가셋 기반 임계값 개선 |
| 답변 생성 | 검색 chunk 기반 template/local LLM 응답 | 고품질 프롬프트 튜닝 |
| 행동 제어 | 시스템 프롬프트와 코드 정책 | 정책 버전 관리 및 평가셋 고도화 |
| 출처 | 문서 ID, chunk ID, 제목, 링크 저장 | 문단 단위 deep link |
| 실패 처리 | no-answer + 워키 질문/요청 티켓 전환 | confidence calibration 고도화 |

## Consequences

- 발표에서 실제 검색 기반 답변 흐름을 보여줄 수 있다.
- 외부 API 키 없이도 RAG 구조를 검증할 수 있다.
- 품질 고도화보다 "근거 있는 답변"과 "업무 전환"을 우선한다.
- 모델 또는 검색 실패는 구조화된 오류 상태로 다음 폴백 단계에 전달한다.
- AI 서버는 Qdrant를 로컬 Vector Store로 고정 사용한다. BE 측 Elasticsearch(ADR 009)와는 별개다.
- Qdrant 장애 또는 데이터 유실 시 MariaDB 정본과 동기화 작업에서 전체 재색인할 수 있어야 한다.
- 지식과 정책을 RAG, 시스템 프롬프트, 코드 규칙으로 분리하여 변경 사항을 즉시 반영할 수 있다.
- LLM provider를 교체해도 검색, 출처 검증, 실패 전환 계약은 유지한다.

## Local RAG Flow

```text
seed manual/worki data
-> chunking
-> local embedding generation
-> vector storage
-> user question
-> question embedding
-> top-k retrieval
-> Cross-Encoder reranking
-> answer generation
-> reference validation
-> chatbot_messages.references_json 저장
-> no-answer이면 워키 질문 또는 요청 티켓 전환
```

## Reranker 반환 계약

Cross-Encoder Reranker는 정렬된 후보와 각 후보의 점수를 함께 반환한다.

```json
{
  "results": [
    {
      "candidateId": "chunk-123",
      "score": 4.82,
      "rank": 1
    }
  ]
}
```

- `candidateId`, `score`, `rank`는 필수다.
- `score`는 Cross-Encoder가 반환한 원본 점수다.
- 모델별 점수 범위가 다를 수 있으므로 정규화 전에는 `0~1` 범위로 해석하지 않는다.
- `NO_RESULT` 판단 임계값은 선택한 모델과 평가셋을 기준으로 별도 설정한다.

## Prompt Policy

| 영역 | 역할 | 적용 방식 |
|---|---|---|
| `base_prompt` | 출처 표시, 거절, 전환 등 핵심 행동 규칙 | 코드·배포 설정으로 고정 |
| `custom_prompt` | 회사/부서 맞춤 지침 | SYSTEM_ADMIN이 내용과 활성 상태 관리 |

런타임 프롬프트:

```text
final_prompt = base_prompt + "\n\n" + custom_prompt
```

출처 최신성 표시:

| 경과 기간 | 표시 |
|---|---|
| 3개월 이하 | 별도 표시 없음 |
| 3개월 ~ 6개월 | "N개월 된 내용입니다" |
| 6개월 초과 | "오래된 내용일 수 있습니다. 확인 후 참고하세요." |

## Open Questions

- seed 문서 범위와 개수 결정 필요.
- 고객사별 로컬/클라우드 provider의 품질 평가 기준을 확정해야 한다.
- Cross-Encoder 점수 정규화와 `NO_RESULT` 임계값을 평가셋으로 확정해야 한다.
