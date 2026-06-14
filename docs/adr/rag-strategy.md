# ADR 002 - RAG Strategy

> 문서 유형: ADR
> 상태: Accepted
> 정본 위치: `docs/adr/rag-strategy.md`
> 관련 문서: `docs/reference/trd.md`, `docs/adr/deployment-and-data-security.md`, `docs/domain-guides/chatbot-rag.md`
> 버전: v0.7
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
- 각 point에는 `_chunk_id`, `text`, `doc_id`, `source_type`, `source_id`, `title`, `chunk_index` payload를 저장한다.
- 검색 metric은 cosine similarity를 기본으로 사용한다.
- collection 생성 시 provider별 vector size를 사용한다. `local`은 1024, `openai`는 1536, `google`은 768이다.
- embedding provider나 모델을 변경할 때 기존 collection 차원과 맞지 않으면 신규 collection을 생성하고 재색인한다.
- point ID는 `{source_type}:{source_id}:{chunk_index}`를 기반으로 생성한 deterministic UUID를 사용한다.
- 부서 R&R과 승인된 라우팅 사례는 청킹하지 않고 `{source_type}:{source_id}:0` 단일 point로 upsert한다.
- 단일 point 수정은 선행 삭제 없이 같은 deterministic ID로 교체하고, 삭제는 `doc_id` payload 기준으로 처리한다.
- deterministic ID가 보장하는 범위는 중복 방지까지다. 동일 source 작업의 순서와 오래된 재시도 무효화는 BE `ai_sync_jobs`가 담당한다.
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

Cross-Encoder Reranker는 정렬된 후보와 각 후보의 본문, 출처, 검색 점수를 함께 반환한다.

```json
{
  "results": [
    {
      "candidateId": "chunk-123",
      "text": "청크 본문",
      "score": 4.82,
      "rank": 1,
      "metadata": {
        "source_type": "MANUAL",
        "source_id": 123
      },
      "retrievalScore": 0.81
    }
  ]
}
```

- `candidateId`, `text`, `score`, `rank`, `metadata`, `retrievalScore`를 반환한다.
- `score`는 Cross-Encoder가 반환한 원본 점수다.
- `retrievalScore`는 Qdrant가 반환한 원본 점수이며 reranker 점수와 혼합하지 않는다.
- 모델별 점수 범위가 다를 수 있으므로 정규화 전에는 `0~1` 범위로 해석하지 않는다.
- `NO_RESULT` 판단 임계값은 선택한 모델과 평가셋을 기준으로 별도 설정한다.

### 모델 수명주기와 오류 처리

- Cross-Encoder는 `@lru_cache(maxsize=1)` 팩토리로 프로세스당 한 번 생성한다.
- FastAPI lifespan에서 팩토리를 호출해 요청 전에 preload한다.
- 모델 로드와 `predict()` 실패는 `ProviderError("cross-encoder", ...)`로 변환한다.
- 질의 임베딩과 Qdrant 호출 실패도 각각 공통 `ProviderError`로 변환한다.
- 조회 경로는 존재하지 않는 collection을 자동 생성하지 않는다.

## 답변 생성 계약

- 답변 생성기는 reranking된 후보의 본문과 출처를 그대로 사용하며 Vector Store를 다시 조회하지 않는다.
- LLM 출력은 `ANSWER` 또는 `INSUFFICIENT_CONTEXT` 상태, 답변, 인용 chunk ID를 가진 JSON으로 제한한다.
- 현재 Local/Ollama adapter인 `langchain_community.ChatOllama`와 동일한 경로를 유지하기 위해 `with_structured_output()` 대신 일반 `invoke()` 결과를 JSON 파싱하고 Pydantic으로 검증한다.
- 자유 텍스트의 특정 문구를 비교해 근거 부족 여부를 판단하지 않는다.
- 검색 후보 없음, 최고 reranker 점수 미달, `INSUFFICIENT_CONTEXT`, 빈 인용, 존재하지 않는 인용 ID는 `NO_RESULT`다.
- 중복 인용 ID는 순서를 유지해 제거하고, 검증된 검색 후보만 최종 references에 포함한다.
- provider 네트워크/API 오류 재시도는 infra 계층이 담당한다. 답변 생성기는 JSON 파싱 또는 스키마 검증 실패에 한해 1회 재시도한다.
- 현재 reranker 임계값 `0.0`은 raw logit 기준 임시값이며 평가셋으로 보정한다.

## 폴백 오케스트레이션 결정

- A 매뉴얼, B 워키, C 승인·수기 지식, D Tool Calling 단계를 `StepRunner` Protocol 구현체로 분리한다.
- 오케스트레이터는 LangGraph 없이 명시적인 Python for-loop와 구조화 상태로 단계를 전환한다.
- `SUCCESS`와 `BLOCKED`는 즉시 종료하고, `NO_RESULT`와 예상 가능한 provider 오류는 다음 단계로 이동한다.
- 모든 단계가 결과를 만들지 못하면 `CREATE_TICKET` 전환 액션을 반환한다.
- 예상하지 못한 구현 예외는 전파한다. 다만 기존 `provider_call()` 내부 예외는 공통 정책에 의해 `ProviderError`로 변환된다.
- `asyncio.wait_for()`와 worker thread를 결합한 단계 timeout은 실행 중인 thread를 취소하지 못한다. 중복 provider 호출을 막기 위해 timeout 시 다음 단계로 폴백하지 않고 오케스트레이션을 `ERROR`로 종료한다.
- provider HTTP timeout을 단계 timeout 이하로 맞추는 것을 근본 해결책으로 둔다.
- 일반 챗봇 요청에는 `custom_prompt`를 노출하지 않으며 신뢰된 BE 내부 계약에서만 전달한다.
- 외부 응답 출처는 Qdrant metadata의 `source_type`, `source_id`를 정본으로 사용한다.

## Prompt Policy

| 영역 | 역할 | 적용 방식 |
|---|---|---|
| `base_prompt` | 출처 표시, 거절, 전환 등 핵심 행동 규칙 | 코드·배포 설정으로 고정 |
| `custom_prompt` | 회사/부서 맞춤 지침 | SYSTEM_ADMIN이 내용과 활성 상태 관리 |

런타임 프롬프트:

```text
final_prompt = base_prompt + "\n\n" + custom_prompt
```

`base_prompt`는 context 외 지식 사용 금지, 근거 부족 상태 반환, 인용 ID 포함, JSON 응답 형식을 강제한다. `custom_prompt`가 기본 규칙과 충돌하면 `base_prompt`를 우선한다.

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
- `doc_id` payload index와 Qdrant scroll pagination을 운영 범위에 포함할지 확정해야 한다.
- provider 또는 모델 변경 시 collection 재색인 운영 절차를 확정해야 한다.
