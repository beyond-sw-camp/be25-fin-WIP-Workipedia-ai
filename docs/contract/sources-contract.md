# AI-BE `sources` 계약 명세

> AI `POST /api/v1/chat` 응답의 `sources` 배열 각 항목 스펙.
> BE는 이 스펙을 기반으로 `rag_citations` 테이블에 저장한다.

## 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `candidate_id` | string | O | Qdrant chunk ID. 일반적으로 `{source_type}:{source_id}:{chunk_index}` 형식이나 보장하지 않음 |
| `source_type` | string | O | 출처 타입. 아래 가능 값 참고 |
| `source_id` | string | O | 원본 도메인의 ID. Qdrant에 int로 저장된 경우도 string으로 변환 |
| `chunk_index` | int? | - | chunk 순번. 없으면 `null` |
| `page_start` | int? | - | PDF 기반 MANUAL chunk의 시작 페이지. txt/docx MANUAL 또는 비해당 타입이면 `null` |
| `page_end` | int? | - | PDF 기반 MANUAL chunk의 끝 페이지. txt/docx MANUAL 또는 비해당 타입이면 `null` |
| `title` | string | O | 원본 문서 제목 |
| `score` | float | O | rerank 점수 |

## `source_type` 가능 값

| 값 | 설명 | 검색 collection |
|----|------|----------------|
| `MANUAL` | 사내 매뉴얼 PDF | `manual_chunks` |
| `WORKI` | 워키 게시글 | `worki_chunks` |
| `KNOWLEDGE_DATA` | 지식 데이터 | `knowledge_data_chunks` |
| `MANUAL_KNOWLEDGE` | 매뉴얼 기반 지식 | `manual_knowledge_chunks` |

## 출처 필드 채우기 우선순위

1. **Qdrant payload metadata** (`source_type`, `source_id`, `chunk_index`, `title`, `page_start`, `page_end`)
2. **`candidate_id` 파싱 fallback** — metadata 누락 시 `{source_type}:{source_id}:{chunk_index}` 파싱
3. **skip** — 둘 다 실패하면 해당 source를 제외하고 warning 로그 기록 (500 에러 없음)

## AI 동작 보장

- `source_type`/`source_id`가 metadata와 `candidate_id` 파싱 모두에서 확인 불가능한 candidate는 `sources`에서 제외된다 (500 에러 없음).
- `source_id`는 항상 string으로 반환된다 (Qdrant에 int로 저장된 경우도 변환).
- AI는 인용수를 관리하지 않는다. 최종 답변에 실제로 사용된 출처만 반환한다.

## BE 저장 정책

- AI가 반환한 `sources` 전체를 `rag_citations`에 원천 row로 저장한다.
- 중복 제거 및 집계 정책은 조회 쿼리에서 결정한다.
- FAQ 인기 매뉴얼은 `source_type = 'MANUAL'`만 집계한다.
