# Department Routing Prompt Guide

> 문서 유형: Development Guide
> 상태: Draft
> 대상: 챗봇/RAG 담당자
> 최종 수정: 2026-06-09

## 목적

관리자가 자연어로 부서 역할 설명을 입력하면 AI 서버가 부서별 routing prompt를 생성해서 반환한다.

관리자는 관리자 설정 화면의 공용 입력창에 자연어로 부서 역할 설명을 입력한다.

예:

```text
개발 1팀은 ERP와 IT를 담당하고 개발 2팀은 RAG와 검색을 담당한다
```

AI 서버는 등록된 부서와 현재 prompt를 기준으로 자연어 수정 의도를 해석한다. 문자열을 잘라 붙이는 임시 응답은 사용하지 않는다.

## API 계약

BE가 AI 서버에 다음 형식으로 요청한다.

`POST /api/v1/department/routing-prompt`

요청 body:

```json
{
  "instruction": "개발 2팀에 RAG도 추가해줘",
  "targets": [
    {
      "departmentId": 1,
      "departmentName": "개발 1팀",
      "currentPrompt": "개발 1팀은 ERP를 담당한다."
    },
    {
      "departmentId": 2,
      "departmentName": "개발 2팀",
      "currentPrompt": "개발 2팀은 검색을 담당한다."
    }
  ]
}
```

응답 body:

```json
{
  "results": [
    {
      "departmentId": 2,
      "routingPrompt": "개발 2팀은 검색과 RAG를 담당한다."
    }
  ]
}
```

- 변경이 필요한 부서만 응답에 포함한다.
- 응답에 없는 부서는 BE가 변경하지 않는다.

## 기대 동작

AI 서버는 입력 문장을 그대로 잘라 붙이는 것이 아니라, 부서별 최종 역할 설명을 만들어야 한다.

삭제/수정 예:

관리자 입력:
```text
개발 2팀에서 검색은 빼고 RAG만 담당하게 해줘
```

AI 응답:
```json
{
  "results": [
    {
      "departmentId": 2,
      "routingPrompt": "개발 2팀은 RAG를 담당한다."
    }
  ]
}
```

## 구현 기준

- 현재 API 등록 지점은 `app/api/v1/router.py`다.
- 부서 routing prompt 기능은 구현 시 별도 department domain 모듈로 분리한다.
- AI 호출 실패 시 임시 문자열 응답을 반환하지 않고 명시적인 오류를 반환한다.

## 주의 사항

- 부서 routing prompt는 티켓 자동 배정과 RAG 검색에 사용되므로 문장은 명확하고 짧게 유지한다.
- 민감정보가 응답에 포함되지 않도록 검증한다.
- AI 서버는 timeout 내에 응답하고, 실패 원인을 구조화된 오류로 반환해야 한다.
