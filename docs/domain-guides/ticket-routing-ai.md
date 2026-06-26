# Ticket Routing AI Guide

> 문서 유형: Development Guide
>
> 관련 이슈: AI #12, AI #13, AI #31, BE #93, BE #127
>
> 상태: 구현 중
>
> 최종 수정: 2026-06-14

## 목적

티켓 제목과 내용을 관리자 작성 부서 R&R 및 TEAM_ADMIN이 승인한 과거 처리 사례와 비교해 가장 적합한 담당 부서를 결정한다.

AI 서버는 후보 검색, 부서별 reranking, 점수와 점수 차이 계산, `AUTO_ASSIGNED` 또는 `COMMON_QUEUE` 결정을 담당한다. BE는 AI 응답을 저장하고 실제 티켓 상태와 담당 부서를 반영한다. 부서 내부 개인 담당자 배정은 TEAM_ADMIN 책임이다.

## API 계약

```text
POST /api/v1/tickets/routing
```

요청:

```json
{
  "title": "ERP 계정 접근 불가",
  "content": "ERP 시스템에 로그인이 안 됩니다",
  "sourceChatbotMessageId": 123
}
```

`sourceChatbotMessageId`는 선택 필드다. 챗봇을 거치지 않은 일반 티켓은 `null` 또는 필드 생략을 허용한다.

자동 배정 응답:

```json
{
  "assignedDepartmentId": 2,
  "assignedDepartmentName": "개발1팀",
  "confidenceScore": 5.14,
  "scoreMargin": 1.27,
  "decision": "AUTO_ASSIGNED",
  "reasons": ["1위 점수 5.14, 1·2위 점수 차 1.27로 자동 배정 기준 통과"],
  "candidateDepartments": [
    {
      "departmentId": 2,
      "departmentName": "개발1팀",
      "confidenceScore": 5.14
    },
    {
      "departmentId": 5,
      "departmentName": "개발2팀",
      "confidenceScore": 3.87
    }
  ],
  "model": "bongsoo/kpf-cross-encoder-v1",
  "provider": "cross-encoder"
}
```

공통 접수 큐 응답:

```json
{
  "assignedDepartmentId": null,
  "assignedDepartmentName": null,
  "confidenceScore": null,
  "scoreMargin": null,
  "decision": "COMMON_QUEUE",
  "reasons": ["후보 부서가 1개뿐이어서 자동 배정하지 않음"],
  "candidateDepartments": [
    {
      "departmentId": 3,
      "departmentName": "개발3팀",
      "confidenceScore": 2.1
    }
  ],
  "model": "bongsoo/kpf-cross-encoder-v1",
  "provider": "cross-encoder"
}
```

threshold 또는 margin 미달이어도 계산된 후보는 운영 추적을 위해 유지한다. Cross-Encoder 자체가 실패한 경우에는 유효한 reranking 점수가 없으므로 후보 목록을 비워 반환한다.

## JSON 필드 규칙

BE 계약은 camelCase이고 Python 내부 필드는 snake_case다. 요청·응답 Pydantic 모델에 같은 alias 설정을 적용한다.

```python
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class RoutingModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
```

FastAPI endpoint는 `response_model_by_alias=True`로 응답을 직렬화한다.

## Vector Store

인덱싱은 AI #13 범위다.

| collection | 데이터 | 등록 주체 |
|---|---|---|
| `routing_dept_rr` | 부서 R&R | SYSTEM_ADMIN |
| `routing_cases` | 승인된 처리 사례 | TEAM_ADMIN |

R&R payload 예:

```text
chunk_id: ROUTING_RR:{department_id}:{chunk_index}
text: "개발1팀은 ERP와 IT 시스템을 담당한다"
metadata:
  department_id: 1
  department_name: "개발1팀"
  type: "rr"
```

처리 사례 payload 예:

```text
chunk_id: ROUTING_CASE:{routing_case_id}:{chunk_index}
text: "ERP 계정 잠금 문제를 해결했다"
metadata:
  department_id: 1
  department_name: "개발1팀"
  type: "case"
```

`department_id` 또는 `department_name`이 없는 검색 결과는 응답 후보로 사용할 수 없으므로 제외한다.

## 라우팅 지식 동기화 API

부서 R&R과 승인된 처리 사례는 BE가 AI 내부 API로 단건 동기화한다. 기존 매뉴얼·워키·승인 지식·수기 지식의 파일 업로드 인덱싱 경로와 분리하며, 라우팅 지식은 청킹하지 않고 source당 point 하나로 저장한다.

```text
POST /api/v1/knowledge/sync
DELETE /api/v1/knowledge/{source_id}?sourceType=DEPT_RR
```

등록·수정 요청:

```json
{
  "sourceId": 3,
  "sourceType": "DEPT_RR",
  "title": "개발1팀 R&R",
  "content": "개발1팀은 RAG 파이프라인과 LLM 연동을 담당한다.",
  "departmentId": 3,
  "departmentName": "개발1팀"
}
```

등록·수정 응답:

```json
{
  "sourceId": 3,
  "syncedChunks": 1
}
```

삭제 응답:

```json
{
  "sourceId": 3,
  "deletedChunks": 1
}
```

없는 데이터를 삭제해도 멱등 성공으로 처리하고 `deletedChunks: 0`을 반환한다.

### 입력 계약

- `sourceType`은 `DEPT_RR`, `ROUTING_CASE`만 허용한다.
- `sourceId`와 `departmentId`는 0보다 커야 한다.
- `title`, `content`, `departmentName`은 공백 문자열을 허용하지 않는다.
- `DEPT_RR`의 `sourceId`는 부서 ID이며 `departmentId`와 같아야 한다.
- `ROUTING_CASE`의 `sourceId`는 부서 ID가 아니라 승인된 라우팅 사례의 고유 ID다.
- 요청·응답 JSON은 camelCase, Python 내부 필드는 snake_case로 관리한다.

### 저장 계약

| sourceType | collection | metadata `type` |
|---|---|---|
| `DEPT_RR` | `routing_dept_rr` | `rr` |
| `ROUTING_CASE` | `routing_cases` | `case` |

저장 본문과 임베딩 입력은 모두 `title + "\n" + content`다. 논리 chunk ID는 `{sourceType}:{sourceId}:0`, `doc_id`는 `{sourceType}:{sourceId}`이며 Qdrant adapter가 논리 chunk ID를 deterministic UUID point ID로 변환한다.

```json
{
  "doc_id": "ROUTING_CASE:105",
  "source_type": "ROUTING_CASE",
  "source_id": 105,
  "title": "ERP 접근 장애 처리 사례",
  "department_id": 3,
  "department_name": "개발1팀",
  "type": "case"
}
```

라우팅 지식은 1청크 고정이므로 수정 시 선행 삭제 없이 같은 ID로 upsert한다. 동일 요청의 재호출은 같은 point를 교체하며 중복 point를 만들지 않는다. DELETE는 `doc_id` 기준으로 삭제한다.

deterministic ID는 작업 순서를 보장하지 않는다. 동일 source의 최신 작업 우선, 오래된 실패 작업 무효화, UPSERT 이후 DELETE 정합성은 BE #84의 `ai_sync_jobs` 워커가 보장한다. AI API는 deterministic ID 기반 멱등 저장과 삭제를 담당한다.

### 동기화 오류 계약

| 상황 | 처리 |
|---|---|
| 필수 필드 누락, 공백, 0 이하 ID | HTTP 422 |
| `DEPT_RR`의 `sourceId`와 `departmentId` 불일치 | HTTP 422 |
| embedding 또는 Qdrant 실패 | HTTP 500 |
| 삭제 대상 없음 | HTTP 200, `deletedChunks: 0` |

provider 내부 오류는 응답에 노출하지 않는다. 마스킹은 AI #31 후속 범위이며, 적용 전에는 BE가 개인정보를 포함하지 않은 라우팅 지식만 전달한다. 로컬·클라우드 embedding provider는 모두 허용한다.

## 처리 파이프라인

```text
title + content
→ embedding 1회 생성
→ 같은 embedding으로 routing_dept_rr top 20 검색
→ 같은 embedding으로 routing_cases top 20 검색
→ department_id 기준 그룹화
→ 부서별 vector max score로 상위 3개 부서 선택
→ 부서별 R&R 상위 1개 + 사례 상위 3개 context 구성
→ Cross-Encoder로 부서 후보 reranking
→ topScore와 scoreMargin 계산
→ AUTO_ASSIGNED 또는 COMMON_QUEUE 결정
```

### Embedding 재사용

기존 `RagRetriever.search()`는 질의를 직접 임베딩한다. 라우팅은 두 collection에 같은 벡터를 사용하므로 `search_by_embedding()`을 별도로 제공한다.

```python
def search_by_embedding(
    embedding: list[float],
    collection_name: str,
    top_k: int,
) -> list[RagCandidate]: ...
```

`search()`는 기존 호환성을 유지하면서 내부에서 embedding을 생성한 뒤 `search_by_embedding()`에 위임한다.

### 부서 후보 구성

각 부서 그룹은 R&R 청크와 사례 청크를 구분해 보존한다.

```text
대표 vector score = 그룹 내 모든 청크의 max score
Cross-Encoder context = R&R 상위 1개 + 사례 상위 3개
```

Cross-Encoder 입력이 모델 최대 길이를 넘으면 모델 tokenizer의 기본 truncation 규칙을 따른다.

## Decision 규칙

AI가 `decision`을 직접 계산한다.

| 조건 | 결과 |
|---|---|
| 검색 결과 없음 | `COMMON_QUEUE` |
| 유효한 metadata를 가진 부서 없음 | `COMMON_QUEUE` |
| Qdrant 연결·조회 실패 | HTTP 500 |
| Cross-Encoder 실패 | `COMMON_QUEUE`, 후보 목록 없음 |
| 후보 부서 1개 + 점수 >= `routing_single_score_threshold` | `AUTO_ASSIGNED` |
| 후보 부서 1개 + 점수 < `routing_single_score_threshold` | `COMMON_QUEUE` |
| 1위 점수 < `routing_score_threshold` | `COMMON_QUEUE` |
| 1·2위 점수 차 < `routing_margin_threshold` | `COMMON_QUEUE` |
| 1위 점수와 점수 차 모두 통과 | `AUTO_ASSIGNED` |

후보가 하나뿐이면 score margin을 계산할 수 없으므로 `routing_single_score_threshold`만 기준으로 자동 배정 여부를 판단한다.

Cross-Encoder 점수는 raw score이며 `0~1` 확률로 해석하지 않는다.

## 설정

운영 중 조정할 값:

```python
class Settings(BaseSettings):
    routing_score_threshold: float = 0.0
    routing_single_score_threshold: float = 0.75
    routing_margin_threshold: float = 0.5
```

환경변수:

```text
ROUTING_SCORE_THRESHOLD
ROUTING_SINGLE_SCORE_THRESHOLD
ROUTING_MARGIN_THRESHOLD
```

코드 상수:

```python
ROUTING_RETRIEVAL_TOP_K = 20
ROUTING_RERANK_TOP_K = 3
ROUTING_DEPT_RR_COLLECTION = "routing_dept_rr"
ROUTING_CASES_COLLECTION = "routing_cases"
```

현재 임계값은 평가셋 확보 전 초기값이다. 한국어 사내 티켓 평가셋의 자동 배정 정확도, 공통 큐 비율, p95 latency를 측정해 보정한다.

## 모듈 구조

```text
app/
├── api/v1/endpoints/ticket_routing.py
├── api/v1/endpoints/knowledge_sync.py
├── domain/ticket_routing/
│   ├── __init__.py
│   ├── schemas.py
│   └── service.py
├── domain/knowledge_sync/
│   ├── __init__.py
│   ├── schemas.py
│   └── service.py
├── domain/rag/
│   ├── retriever.py
│   └── reranker/cross_encoder_reranker.py
└── core/config.py
```

역할:

| 컴포넌트 | 책임 |
|---|---|
| `TicketRoutingRequest` | 요청 검증, camelCase alias, 공백 입력 차단 |
| `TicketRoutingResponse` | BE `RoutingResult` 계약 반환 |
| `TicketRoutingService` | 검색, 그룹화, reranking, decision 조율 |
| `RagRetriever.search_by_embedding()` | 기존 embedding으로 Qdrant 검색 |
| `CrossEncoderReranker` | 부서 후보 relevance score 계산 |
| `ticket_routing.py` | HTTP 계약과 provider 오류 변환 |
| `KnowledgeSyncRequest` | source type, ID 정합성, 공백 입력 검증 |
| `KnowledgeSyncService` | 라우팅 지식 embedding, deterministic upsert, 삭제 |
| `knowledge_sync.py` | 동기화·삭제 HTTP 계약과 provider 오류 변환 |

## 오류 계약

| 상황 | 처리 |
|---|---|
| title/content 누락 또는 공백 | HTTP 422 |
| embedding provider 실패 | HTTP 500 |
| Qdrant 장애·collection 미존재 | HTTP 500 |
| 검색 결과 없음 | `COMMON_QUEUE` 정상 응답 |
| metadata가 유효한 후보 없음 | `COMMON_QUEUE` 정상 응답 |
| 후보 부서 1개 | `COMMON_QUEUE` 정상 응답 |
| Cross-Encoder 실패 | `COMMON_QUEUE` 정상 응답 |

endpoint는 외부 provider 오류의 내부 메시지를 그대로 노출하지 않고 일반화된 500 응답을 반환한다.

## 테스트 범위

- `search_by_embedding()` 정상 결과, 빈 결과, `top_k <= 0`, Qdrant 오류
- 기존 `search()`의 embedding 생성과 검색 위임 회귀 테스트
- 점수와 margin 통과 시 자동 배정
- 검색 결과 없음, 유효 metadata 없음, 후보 1개
- top score 미달과 margin 미달
- Cross-Encoder 실패 시 공통 큐
- camelCase 요청·응답
- nullable `sourceChatbotMessageId`
- title/content 공백 또는 누락 시 422
- 라우팅 지식 source type별 collection과 metadata `type`
- 동일 라우팅 지식 재호출 시 같은 논리 chunk ID 사용
- `DEPT_RR`의 `sourceId`와 `departmentId` 불일치 및 공백 입력 시 422
- embedding 실패 시 upsert 미호출
- Qdrant upsert·삭제 실패 시 내부 메시지를 숨긴 HTTP 500
- 없는 라우팅 지식 삭제 시 `deletedChunks: 0`
- 동기화·삭제 응답 camelCase
- 기존 RAG 테스트 회귀

## 처리 사례 기반 동적 갱신

모델을 재학습하거나 부서 벡터를 직접 이동시키지 않는다. 최종 처리 결과가 확정된 티켓만 해당 부서의 검색 사례로 추가한다.

```text
최초 추천 부서에서 이관
→ 최종 부서가 수락하고 처리 완료
→ TEAM_ADMIN이 라우팅 사례 반영 승인
→ AI #13 인덱싱
→ 최종 처리 부서의 승인 사례로 routing_cases에 저장
```

다음 상황만으로는 사례를 확정하지 않는다.

- AI가 특정 부서를 추천한 시점
- 다른 부서로 이관을 요청한 시점
- 사용자 취소 또는 업무량 분산 목적의 이관
- 최종 처리되지 않은 티켓

신규 부서는 SYSTEM_ADMIN의 R&R만으로 시작하고, 승인 사례가 쌓이면 같은 부서 context에 함께 사용한다.

## 보안 후속 범위

데이터 유형별 마스킹 정책은 AI #31에서 별도로 정리한다. 라우팅 사례 인덱싱과 실시간 티켓 질의의 마스킹 수준은 해당 이슈의 확정안을 따른다.

원문과 개인정보를 로그에 직접 남기지 않는 원칙은 유지한다.

## 남은 결정

- 승인 사례의 부서별 최대 보관 수와 시간 감쇠
- 동일·유사 사례 중복 제거 기준
- 평가셋 기반 score·margin 임계값
- reranker 모델 교체 여부
- 자동 배정 전환을 허용할 정확도 기준
