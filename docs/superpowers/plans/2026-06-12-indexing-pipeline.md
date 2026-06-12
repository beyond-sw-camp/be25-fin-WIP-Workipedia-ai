# 문서 인덱싱 파이프라인 구현 현황 및 후속 계획 (이슈 #6)

> 작성일: 2026-06-12
> 최종 수정: 2026-06-12
> 상태: 핵심 구현 완료, 검증 및 운영 보강 진행 필요

## 목표

BE가 전달한 문서를 마스킹·청킹·임베딩하여 Qdrant에 저장하고, 수정·삭제 시 동일 문서의 기존 point를 정리한다.

## 구현 결과

### 완료된 작업

- [x] `DocumentIndexRequest`, `DocumentIndexResponse`, `DocumentDeleteResponse`
- [x] `POST /api/v1/documents/ingest`
- [x] `DELETE /api/v1/documents/{source_id}?source_type=...`
- [x] source type별 Qdrant collection 매핑
- [x] source type별 청킹 크기와 overlap
- [x] `WORKI`의 전화번호·이메일 추가 마스킹
- [x] 임베딩 성공 후 기존 point 삭제
- [x] deterministic UUID point ID
- [x] cosine metric collection 생성
- [x] upsert, query, ID 삭제, `doc_id` filter 삭제
- [x] 서비스 단위 테스트 작성
- [x] ChromaDB dependency 제거와 `qdrant-client` 적용

관련 커밋:

- `e528631` 문서 인덱싱 파이프라인 구현
- `6149c13` ChromaDB에서 Qdrant로 전환
- `a9ad21b` provider와 설정 상수 구조 정리

## 현재 계약

### Collection

```python
COLLECTION_MAP = {
    "MANUAL": "manual_chunks",
    "WORKI": "worki_chunks",
    "KNOWLEDGE_DATA": "knowledge_data_chunks",
    "MANUAL_KNOWLEDGE": "manual_knowledge_chunks",
}
```

### 청킹

```python
CHUNK_CONFIG = {
    "MANUAL": {"chunk_size": 800, "chunk_overlap": 200},
    "WORKI": {"chunk_size": 300, "chunk_overlap": 50},
    "KNOWLEDGE_DATA": {"chunk_size": 600, "chunk_overlap": 150},
    "MANUAL_KNOWLEDGE": {"chunk_size": 800, "chunk_overlap": 200},
}
```

### 처리 순서

```text
source_type 검증
→ masker_for(source_type)
→ chunk_text(..., **CHUNK_CONFIG[source_type])
→ embed_texts
→ delete_by_doc_id
→ upsert
```

임베딩 실패 전에는 기존 point를 삭제하지 않는다.

## 검증 현황

작성된 서비스 테스트는 다음을 확인한다.

- 인덱싱 chunk 수 반환
- embed → delete → upsert 순서
- 임베딩 실패 시 기존 point 보존
- 잘못된 source type 거절
- 공백 텍스트 거절
- `WORKI` 추가 마스킹
- `MANUAL` 선택 마스킹 제외
- source type별 청킹 설정
- source type별 collection
- 삭제된 chunk 수 반환

2026-06-12 기본 실행 결과는 테스트 실패가 아니라 **테스트 수집 전 설정 오류**다.

```text
ValidationError: embedding_provider
현재 .env 값: local
허용값: ollama, openai, google
```

환경변수를 명령에 주입한 코드 검증은 완료했다.

```bash
EMBEDDING_PROVIDER=ollama .venv/bin/python -m pytest tests/domain/document/test_document_service.py -v
# 12 passed

EMBEDDING_PROVIDER=ollama .venv/bin/python -m pytest tests/ -q
# 12 passed

EMBEDDING_PROVIDER=ollama .venv/bin/python -c "from app.api.v1.endpoints.documents import router; print('OK')"
# OK
```

따라서 남은 문제는 코드 실패가 아니라 `.env` 기본값을 최신 provider 이름으로 변경하는 작업이다.

## 후속 Task 1: 환경 설정 정합성

- [ ] `.env.example`을 만들거나 최신 provider 허용값을 문서화
- [ ] 기존 `EMBEDDING_PROVIDER=local` 값을 `ollama`로 migration
- [ ] CI에서 잘못된 enum 값이 즉시 드러나는 config import 테스트 추가

## 후속 Task 2: Qdrant 운영 보강

- [ ] `doc_id` payload index 생성
- [ ] 필요 시 `source_id`, `source_type` payload index 추가
- [ ] Qdrant timeout과 연결 실패를 공통 `WorkipediaException`으로 변환
- [ ] collection 생성 경쟁 조건 처리
- [ ] 대량 문서의 scroll pagination 처리
- [ ] snapshot과 RDB 정본 기반 전체 재색인 절차 문서화

현재 `delete_by_doc_id()`는 `limit=10000` 단일 scroll만 수행한다. 문서 하나가 10,000개를 초과하는 chunk로 분할될 가능성은 낮지만, adapter의 일반 계약으로는 pagination을 지원하는 편이 안전하다.

## 후속 Task 3: 임베딩 차원 관리

현재 `QDRANT_VECTOR_SIZE=1024`는 `bge-m3` 기준이다.

- [ ] provider별 vector size 매핑 추가
- [ ] collection 생성 시 선택 provider의 vector size 사용
- [ ] 기존 collection과 vector size 불일치 감지
- [ ] 모델 변경 시 새 collection 생성과 재색인

`text-embedding-3-small` 등 다른 차원의 모델을 선택하면서 기존 1024차원 collection을 사용하면 upsert가 실패한다.

## 후속 Task 4: 통합 테스트

Docker Qdrant를 실행한 상태에서 다음 흐름을 검증한다.

1. `MANUAL` 문서를 인덱싱한다.
2. 동일 문서를 수정해 재인덱싱한다.
3. 이전 chunk가 검색되지 않는지 확인한다.
4. query 결과의 `_chunk_id`, 본문, 출처 metadata를 확인한다.
5. 문서를 삭제하고 검색 결과에서 사라지는지 확인한다.
6. `WORKI`와 `MANUAL`이 서로 다른 collection에 저장되는지 확인한다.

검증 명령 예시:

```bash
docker compose up -d qdrant
.venv/bin/python -m pytest tests/integration -v
```

통합 테스트 디렉터리는 아직 존재하지 않으므로 작성이 필요하다.

## 완료 기준

- [x] 유효한 provider 환경값에서 현재 단위 테스트 12개 통과
- [x] 유효한 provider 환경값에서 config와 documents router import 통과
- [ ] 실제 Qdrant 통합 테스트 통과
- [ ] provider별 vector size 처리
- [ ] payload index 생성
- [ ] Qdrant 장애가 구조화된 오류로 반환됨
- [ ] 재색인과 삭제가 운영 데이터 규모에서도 누락 없이 동작함
