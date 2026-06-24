# 매뉴얼 변경사항 AI 요약

BE가 매뉴얼 본문 변경(PDF 교체) 시 생성한 diff를 한 줄로 요약해 반환한다.

## 엔드포인트

`POST /api/v1/manual/change-summary`

요청:
```json
{ "title": "위키피디아 소개서", "contentDiff": "@@ line 12 @@\n- 이전 문구\n+ 새 문구", "updateReason": "PDF_UPLOAD" }
```

응답:
```json
{ "summary": "제3조 제2항의 휴가 신청 기한이 7일 전에서 3일 전으로 변경되었습니다." }
```

## 동작

- `get_llm()` factory(provider 무관)로 LLM을 호출해 사용자용 한국어 한 문장을 생성한다.
- 변경된 위치(조·항·호 번호, 없으면 항목 제목)와 변경 내용을 함께 짚도록 프롬프트로 지시한다.
- 프롬프트는 diff 기호·내부 코드 노출을 금지하고 사용자 관점 요약만 허용한다.
- 마스킹은 적용하지 않는다(사내 매뉴얼 문구, PII 위험 낮음).
- LLM 실패·빈 응답은 500으로 반환하며, 호출 측(BE 워커)이 재시도한다.

## 호출 측

- BE `HttpManualChangeSummaryAiClient`가 aisync 워커에서 비동기로 호출한다.
- source_type `MANUAL_CHANGE_SUMMARY`, source_id = `manual_version_id`.
