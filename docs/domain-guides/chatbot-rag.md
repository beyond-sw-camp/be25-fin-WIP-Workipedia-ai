# Chatbot/RAG Domain Guide

> 문서 유형: Development Guide
> 상태: Draft
> 정본 위치: `docs/domain-guides/chatbot-rag.md`
> 관련 문서: `docs/adr/rag-strategy.md`, `docs/adr/local-llm-security-strategy.md`, `docs/reference/ai-architecture-overview.md`
> 버전: v0.3
> 최종 수정: 2026-06-09

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
- 고객사별 local/cloud embedding provider adapter
- top-k 검색
- Cross-Encoder reranking
- 출처 포함 답변 반환
- `references` 저장
- 답변 없음/불충분 시 요청 티켓 전환 액션 반환
- 개인정보 마스킹 기본 케이스
- RAG 기반 지식 제공
- SYSTEM_ADMIN용 custom_prompt 내용·활성 상태 관리
- 출처 최신성 표시

## API/DB 영향

- `chatbot_sessions`
- `chatbot_messages`
- `chatbot_messages.references_json`
- `ai_prompt_settings` (`custom_prompt`만 관리자 편집)
- `knowledge_data`
- manual/worki chunks
- embedding adapter
- chatbot query API
- Spring Boot ↔ Python AI 서버 API

## 권한/보안 체크

- 출처 없는 답변 금지
- 개인정보 저장 전 마스킹
- 클라우드 provider 호출 전 민감정보 마스킹
- 근거 부족 시 그럴듯한 답변 생성 금지
- QLoRA 및 파인튜닝 파이프라인은 사용하지 않는다.

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

## 완료 기준

- 질문을 입력하면 챗봇 메시지가 저장된다.
- 근거가 있으면 매뉴얼/워키 출처와 함께 답변한다.
- 근거가 없으면 요청 티켓 전환 액션을 반환한다.
- `references`에 문서 ID, chunk ID, 제목, 링크가 남는다.
- 오래된 출처는 최신성 경고와 함께 표시된다.
- local/cloud provider가 동일한 응답 계약을 제공한다.

## 논의 필요 사항

- seed 문서 개수와 내용
- 문서 유형별 chunk 크기와 overlap
- Cross-Encoder 점수 정규화와 `NO_RESULT` 임계값
