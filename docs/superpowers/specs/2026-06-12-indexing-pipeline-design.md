# 문서 인덱싱 파이프라인 설계 (이슈 #6)

> 작성일: 2026-06-12
> 최종 수정: 2026-06-12
> 상태: 구현 완료, 환경 설정 및 Qdrant 통합 검증 필요
> 관련 이슈: https://github.com/beyond-sw-camp/be25-fin-WIP-Workipedia-ai/issues/6

## 범위

BE가 전달한 텍스트와 메타데이터를 민감정보 마스킹 → 문서 유형별 청킹 → 임베딩 → Qdrant 저장 순서로 처리한다. 같은 문서의 재인덱싱과 삭제 API도 제공한다.

## 현재 구현

| 영역 | 구현 위치 | 상태 |
|---|---|---|
| 요청·응답 스키마 | `app/domain/document/schemas.py` | 완료 |
| 인덱싱·삭제 API | `app/api/v1/endpoints/documents.py` | 완료 |
| 마스킹·청킹·임베딩 조립 | `app/domain/document/service.py` | 완료 |
| source type별 청킹 설정 | `app/core/config.py`의 `CHUNK_CONFIG` | 완료 |
| source type별 collection | `app/core/config.py`의 `COLLECTION_MAP` | 완료 |
| Qdrant CRUD adapter | `app/infra/vector_store/qdrant_store.py` | 완료 |
| 서비스 단위 테스트 | `tests/domain/document/test_document_service.py` | 12개 통과 |
| 실제 Qdrant 통합 테스트 | 로컬 Docker Qdrant 필요 | 미검증 |
| payload index 생성 | Qdrant adapter | 미구현 |

## 처리 흐름

```text
POST /api/v1/documents/ingest
→ DocumentService.index(request)
→ source_type 검증 및 collection 선택
→ masker_for(source_type).mask(text)
→ chunk_text(masked_text, **CHUNK_CONFIG[source_type])
→ embed_texts(chunks)
→ qdrant_store.delete_by_doc_id(doc_id)
→ qdrant_store.upsert(...)
→ DocumentIndexResponse
```

임베딩을 먼저 완료한 후 기존 point를 삭제한다. 임베딩 provider가 실패하면 기존 검색 데이터를 유지하고 `500` 오류를 반환한다.

```text
DELETE /api/v1/documents/{source_id}?source_type=MANUAL
→ DocumentService.delete(source_id, source_type)
→ qdrant_store.delete_by_doc_id(doc_id)
→ DocumentDeleteResponse
```

## API 계약

### 인덱싱

`POST /api/v1/documents/ingest`

```json
{
  "source_id": 123,
  "source_type": "MANUAL",
  "title": "휴가 신청 절차",
  "text": "1. 결재 시스템에 접속하여..."
}
```

```json
{
  "source_id": 123,
  "indexed_chunks": 20
}
```

### 삭제

`DELETE /api/v1/documents/123?source_type=MANUAL`

```json
{
  "source_id": 123,
  "deleted_chunks": 20
}
```

지원하는 `source_type`:

- `MANUAL`
- `WORKI`
- `KNOWLEDGE_DATA`
- `MANUAL_KNOWLEDGE`

## Collection 정책

| source_type | Qdrant collection |
|---|---|
| `MANUAL` | `manual_chunks` |
| `WORKI` | `worki_chunks` |
| `KNOWLEDGE_DATA` | `knowledge_data_chunks` |
| `MANUAL_KNOWLEDGE` | `manual_knowledge_chunks` |

지식 RAG의 C단계에서는 `KNOWLEDGE_DATA`와 `MANUAL_KNOWLEDGE` collection을 각각 검색한 후 후보를 합쳐 reranking한다. 수기 지식은 별도 E단계가 아니다.

## ID와 payload

- 논리 chunk ID: `{source_type}:{source_id}:{chunk_index}`
- 문서 삭제 키: `{source_type}:{source_id}`
- Qdrant point ID: 논리 chunk ID를 UUID v5로 변환한 deterministic UUID
- distance metric: cosine similarity

```json
{
  "_chunk_id": "MANUAL:123:0",
  "text": "청크 본문",
  "doc_id": "MANUAL:123",
  "source_type": "MANUAL",
  "source_id": 123,
  "title": "휴가 신청 절차",
  "chunk_index": 0
}
```

재인덱싱과 삭제는 `doc_id` payload filter를 사용한다. `doc_id` payload index 생성은 후속 작업이다.

## 유형별 처리

`CHUNK_CONFIG`:

| source_type | chunk_size | chunk_overlap |
|---|---:|---:|
| `MANUAL` | 800 | 200 |
| `WORKI` | 300 | 50 |
| `KNOWLEDGE_DATA` | 600 | 150 |
| `MANUAL_KNOWLEDGE` | 800 | 200 |

마스킹:

- 모든 유형: 주민등록번호, 카드번호
- `WORKI`: 전화번호, 이메일 추가

## 임베딩과 vector size

지원 provider는 `ollama`, `openai`, `google`이다. 현재 Qdrant vector size 상수는 `bge-m3` 기준 `1024`로 고정되어 있다.

임베딩 provider를 바꿀 때 출력 차원이 다르면 기존 collection을 재사용할 수 없다. provider별 vector size 설정과 신규 collection 재색인 절차가 추가로 필요하다.

## 오류 계약

| 상황 | 응답 |
|---|---|
| 마스킹 실패 | `400` |
| 빈 텍스트 | `422` |
| 지원하지 않는 `source_type` | `422` |
| 임베딩 실패 | `500`, 기존 point 유지 |
| Qdrant 호출 실패 | 공통 예외 처리 보강 필요 |

## 현재 검증 상태

2026-06-12 기준 `.env`의 `EMBEDDING_PROVIDER=local`은 최신 enum과 맞지 않아 환경변수 주입 없이 실행하면 테스트 수집 전에 실패한다.

```text
허용값: ollama | openai | google
현재값: local
```

파일을 수정하지 않고 `EMBEDDING_PROVIDER=ollama`를 주입한 검증은 통과했다.

```bash
EMBEDDING_PROVIDER=ollama .venv/bin/python -m pytest tests/domain/document/test_document_service.py -v
# 12 passed

EMBEDDING_PROVIDER=ollama .venv/bin/python -m pytest tests/ -q
# 12 passed

EMBEDDING_PROVIDER=ollama .venv/bin/python -c "from app.api.v1.endpoints.documents import router; print('OK')"
# OK
```

## 완료 조건

- [x] Qdrant adapter와 source type별 collection 구현
- [x] deterministic UUID point ID 구현
- [x] 마스킹 → 청킹 → 임베딩 → 기존 삭제 → upsert 순서 구현
- [x] 삭제 API와 서비스 단위 테스트 작성
- [ ] `.env`의 embedding provider 값을 최신 enum으로 정리
- [x] 유효한 provider 환경값에서 전체 테스트 통과 확인
- [ ] 실제 Qdrant 인덱싱·검색·재인덱싱 통합 검증
- [ ] `doc_id` payload index 생성
- [ ] provider별 vector size와 재색인 정책 구현
