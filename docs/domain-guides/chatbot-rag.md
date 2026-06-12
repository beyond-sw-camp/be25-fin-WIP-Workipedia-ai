# Chatbot/RAG Domain Guide

> 문서 유형: Development Guide
> 상태: Draft
> 정본 위치: `docs/domain-guides/chatbot-rag.md`
> 관련 문서: `docs/adr/rag-strategy.md`, `docs/adr/local-llm-security-strategy.md`, `docs/reference/ai-architecture-overview.md`
> 버전: v0.5
> 최종 수정: 2026-06-12

## 개발 목표

사용자 질문에 대해 매뉴얼/워키를 검색하고, 출처가 있는 답변 또는 요청 티켓 전환 액션을 반환한다.

## 먼저 볼 문서

- `docs/adr/rag-strategy.md`
- `docs/adr/local-llm-security-strategy.md`
- `docs/reference/ai-architecture-overview.md`

## MVP 구현 범위

- 챗봇 세션 생성
- 메시지 저장
- seed 매뉴얼/워키 문서 검색
- Ollama/OpenAI/Google embedding provider adapter
- top-k 검색
- Cross-Encoder reranking
- 출처 포함 답변 반환
- `references` 저장
- 답변 없음/불충분 시 요청 티켓 전환 액션 반환
- 개인정보 마스킹 기본 케이스
- RAG 기반 지식 제공
- SYSTEM_ADMIN용 custom_prompt 내용·활성 상태 관리
- 출처 최신성 표시
- A 매뉴얼 → B 워키 → C 지식 RAG → D Tool Calling 폴백

## API/DB 영향

- `chatbot_sessions`
- `chatbot_messages`
- `chatbot_messages.references_json`
- `ai_prompt_settings` (`custom_prompt`만 관리자 편집)
- `knowledge_data`
- `manual_knowledge`
- manual/worki chunks
- embedding adapter
- chatbot query API
- Spring Boot ↔ Python AI 서버 API

## 권한/보안 체크

- 출처 없는 답변 금지
- AI 로그·Vector Store 저장 전 마스킹
- 클라우드 provider 호출 전 민감정보 마스킹
- 근거 부족 시 그럴듯한 답변 생성 금지
- QLoRA 및 파인튜닝 파이프라인은 사용하지 않는다.

## 민감정보 마스킹

`app/common/masking.py`의 `SensitiveDataMasker`를 인덱싱 경로와 챗봇 질의 경로에서 공용으로 사용한다. BE RDB에는 권한이 통제된 업무 원문을 저장할 수 있지만, AI 로그·Vector Store·클라우드 provider에는 마스킹 전 원문을 남기거나 전달하지 않는다.

기본 패턴:

| 대상 | 마스킹 토큰 | 활성 조건 |
|---|---|---|
| 주민등록번호 | `[주민번호]` | 항상 활성 |
| 16자리 카드번호 | `[카드번호]` | 항상 활성 |
| 전화번호 | `[전화번호]` | `MASKING_PHONE_ENABLED=true` |
| 이메일 | `[이메일]` | `MASKING_EMAIL_ENABLED=true` |

- `MASKING_ENABLED=false`이면 전체 마스킹을 건너뛴다.
- 이미 치환된 마스킹 토큰은 그대로 통과시켜 재인덱싱 시 이중 마스킹을 방지한다.
- 계좌번호는 형식이 다양하고 오탐 위험이 커 별도 정책 확정 후 추가한다.
- 패턴은 생성자에 주입할 수 있어 테스트와 고객사별 확장이 가능하다.
- 탐지된 원문 값은 로그에 기록하지 않는다. 마스킹 적용 여부와 토큰 유형만 기록할 수 있다.

마스킹 처리 중 오류가 발생하면 `app/common/exceptions.py`의 `MaskingBlockedError`를 발생시킨다.

```text
인덱싱 경로
DocumentService
→ SensitiveDataMasker.mask()
→ MaskingBlockedError
→ 인덱싱 중단 및 오류 응답

챗봇 경로
RagOrchestrator
→ SensitiveDataMasker.mask()
→ MaskingBlockedError
→ BLOCKED 안전 응답 후 종료
```

호출 서비스 계층이 `MaskingBlockedError`를 처리하며, 마스킹 모듈은 예외를 공통 예외 타입으로 변환해 전달한다.

## Chunking 책임

BE는 원문과 문서 메타데이터를 AI 서버에 전달하고, AI 서버가 다음 작업을 담당한다.

```text
문서 파싱
→ 민감정보 마스킹
→ 문서 유형별 chunking
→ embedding 생성
→ Vector Store upsert
```

청킹 대상:

- 매뉴얼
- 워키 질문과 채택 답변
- SYSTEM_ADMIN 수기 지식
- TEAM_ADMIN이 승인한 지식화 문서
- TEAM_ADMIN이 승인한 티켓 라우팅 사례

문서 유형별 chunk 크기와 overlap은 코드 설정으로 관리하며 SYSTEM_ADMIN 설정으로 제공하지 않는다.

| source_type | Qdrant collection | chunk_size | overlap |
|---|---|---:|---:|
| `MANUAL` | `manual_chunks` | 800 | 200 |
| `WORKI` | `worki_chunks` | 300 | 50 |
| `KNOWLEDGE_DATA` | `knowledge_data_chunks` | 600 | 150 |
| `MANUAL_KNOWLEDGE` | `manual_knowledge_chunks` | 800 | 200 |

인덱싱 요청:

```text
POST /api/v1/documents/ingest
{ source_id, source_type, title, text }
```

재인덱싱은 임베딩 성공 후 `doc_id={source_type}:{source_id}`인 기존 point를 삭제하고 새 chunk를 upsert한다. 임베딩 실패 시 기존 point를 유지한다.

삭제 요청:

```text
DELETE /api/v1/documents/{source_id}?source_type=MANUAL
```

논리 chunk ID는 `{source_type}:{source_id}:{chunk_index}`이며 Qdrant point ID는 deterministic UUID다.

## Negative Answer

RAG 단계는 다음 구조화 결과를 반환한다.

```json
{
  "status": "SUCCESS",
  "reason": null,
  "answer": "답변 내용",
  "references": [],
  "reranking": {
    "topScore": 4.82,
    "results": [
      {
        "candidateId": "chunk-123",
        "score": 4.82,
        "rank": 1
      }
    ]
  }
}
```

- Reranker 결과에는 후보별 `candidateId`, 원본 `score`, `rank`를 포함한다.
- `topScore`는 1위 후보의 원본 점수다.
- 점수 정규화 방식과 `NO_RESULT` 임계값은 평가셋으로 확정한다.

`status`:

- `SUCCESS`: reranker 점수와 출처 검증을 통과한 답변
- `NO_RESULT`: 검색 결과 없음, 점수 미달, 출처 검증 실패
- `ERROR`: 모델 또는 Vector Store timeout 등 실행 실패
- `BLOCKED`: 민감정보 마스킹 또는 보안 정책 실패

`NO_RESULT`와 재시도 불가능한 `ERROR`는 다음 폴백 단계로 이동한다. `BLOCKED`는 안전 응답 후 종료한다.

## 폴백 단계

```text
A. 매뉴얼 RAG
→ B. 워키 RAG
→ C. 지식 RAG
   - TEAM_ADMIN 승인 지식화 게시판(`KNOWLEDGE_DATA`)
   - SYSTEM_ADMIN 수기 지식(`MANUAL_KNOWLEDGE`)
→ D. Tool Calling
→ 모두 실패하면 워키 등록 또는 요청 티켓 생성 전환 액션
```

- `knowledge_data`와 `manual_knowledge`는 DB·`sourceType`·collection을 통합하지 않는다.
- C단계에서 두 collection의 검색 후보만 합쳐 통합 reranking한다.
- D단계 `NO_RESULT` 또는 재시도 불가능한 `ERROR`는 다음 검색 단계가 아니라 최종 전환 액션으로 처리한다.

## 완료 기준

- 질문을 입력하면 챗봇 메시지가 저장된다.
- 근거가 있으면 매뉴얼/워키 출처와 함께 답변한다.
- 근거가 없으면 요청 티켓 전환 액션을 반환한다.
- `references`에 문서 ID, chunk ID, 제목, 링크가 남는다.
- 오래된 출처는 최신성 경고와 함께 표시된다.
- 지원 provider가 동일한 domain 응답 계약을 제공한다.

## 현재 구현 상태

- 문서 인덱싱·삭제 API와 Qdrant adapter가 구현되어 있다.
- 문서 서비스 단위 테스트 12개는 `EMBEDDING_PROVIDER=ollama` 환경에서 통과한다.
- 실제 Qdrant 통합 테스트, `doc_id` payload index, provider별 vector size 처리는 남아 있다.
- `.env`의 기존 `EMBEDDING_PROVIDER=local` 값은 `ollama`로 변경해야 한다.

## 논의 필요 사항

- seed 문서 개수와 내용
- Cross-Encoder 점수 정규화와 `NO_RESULT` 임계값
- provider별 embedding vector size와 모델 변경 시 재색인 절차
- Qdrant payload index와 통합 테스트 범위
