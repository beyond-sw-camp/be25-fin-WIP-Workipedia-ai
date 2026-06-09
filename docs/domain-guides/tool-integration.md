# Tool Integration Guide

> 상태: Draft  
> 최종 수정: 2026-06-09

## 목적

고객사마다 다른 API와 DB 조회 기능을 코드에 하드코딩하지 않고 등록된 정의를 런타임 Tool로 변환한다.

이 문서에서 DB Tool은 고객사 DB를 로컬/클라우드 DB로 교체한다는 의미가 아니다. Function Calling으로 실행할 데이터 조회 수단을 API 또는 제한된 DB 조회 중에서 선택한다는 의미다.

## 연동 전제

### 고객사가 API를 제공하는 경우

```text
LLM이 API Tool 선택
→ BE가 고객사 API 호출
→ 결과 마스킹
→ LLM이 최종 답변 생성
```

이 방식을 기본 원칙으로 사용한다.

### 고객사가 API를 제공하지 않는 경우

고객사 동의와 네트워크/DB 권한이 확보된 경우에만 DB Tool을 선택적으로 지원한다.

```text
LLM이 DB Tool 선택
→ BE가 사전 등록된 쿼리 템플릿 실행
→ 조회 결과 마스킹
→ LLM이 최종 답변 생성
```

AI가 쿼리문을 새로 생성하거나 DB에서 쿼리문을 가져오는 구조가 아니다. 개발자가 등록하고 검증한 SQL 템플릿에 허용 파라미터만 바인딩해서 실행한다.

## 관리 화면과 권한

### API Tool

SYSTEM_ADMIN이 관리 화면에서 등록하고 활성화한다.

- Tool 이름과 설명
- API endpoint와 HTTP method
- 요청 파라미터 JSON Schema
- 응답 허용 필드
- 인증 방식과 인증정보 참조값
- timeout과 최대 결과 건수
- 활성 여부
- 테스트 호출

### DB Query Tool

API가 없는 고객사에만 선택적으로 제공하며 개발자 권한으로 생성하고 검증한다. SYSTEM_ADMIN은 검증이 끝난 Tool의 활성 여부만 관리한다.

- Tool 이름과 설명
- datasource 식별자
- 사전 정의된 SELECT 쿼리 템플릿
- 입력 파라미터와 타입
- 반환 허용 컬럼
- timeout과 최대 결과 건수
- 테스트 실행 결과와 승인 상태

관리자와 LLM에는 DB 접속정보와 SQL 원문을 노출하지 않는다.

## Tool 정의

필수 항목:

| 필드 | 설명 |
|---|---|
| `name` | LLM에 노출할 고유 Tool 이름 |
| `description` | 사용 조건과 반환 정보 |
| `endpointType` | `HTTP_API` 또는 `DB_QUERY` |
| `endpoint` | API URL 또는 등록된 datasource 식별자 |
| `method` | 허용 HTTP method |
| `parametersSchema` | 허용 파라미터 JSON Schema |
| `responseSchema` | LLM에 전달할 응답 범위 |
| `authType` | API Key, OAuth, Token, None |
| `active` | Tool 활성 여부 |
| `approvalStatus` | DB Query Tool 검증 및 승인 상태 |

## 실행 흐름

```text
DB에서 활성 Tool 정의 조회
→ JSON Schema로 입력 모델 생성
→ LLM에 Tool 목록 바인딩
→ LLM이 Tool과 인자 선택
→ 서버가 허용 범위 검증
→ HTTP/DB adapter 실행
→ 민감정보 마스킹
→ 결과를 LLM에 전달
→ 최종 답변 생성
```

## DB Tool 제한

- API가 없는 고객사에 대한 예외적 연동 방식으로 사용
- 개발자 권한에서만 생성 및 수정
- read-only 계정 사용
- SELECT만 허용
- 단일 쿼리와 파라미터 바인딩만 허용
- 개발자 검증과 승인이 완료된 쿼리 템플릿만 실행
- 임의 SQL 생성 금지
- 허용된 View 또는 컬럼만 조회
- timeout과 최대 결과 건수 설정
- 호출자, Tool, 파라미터, 결과 건수를 감사 로그에 기록

## 오류 처리

- Tool 미선택 또는 결과 없음: 다음 폴백 경로로 이동
- 정의되지 않은 파라미터: 호출 거부
- timeout 또는 연결 실패: 실패 사유 기록 후 다음 폴백 경로로 이동
- 민감정보 마스킹 실패: 결과를 LLM에 전달하지 않음

Tool 실행 결과도 공통 상태인 `SUCCESS`, `NO_RESULT`, `ERROR`, `BLOCKED`로 반환한다. 빈 결과는 `NO_RESULT`, 권한·스키마·마스킹 위반은 `BLOCKED`로 처리한다.

## 구현 경계

- AI 레포: 활성·승인된 Tool 선택, 입력 스키마 검증, Tool 결과 기반 답변
- BE 레포: Tool 정의 CRUD, 권한과 승인 상태, 인증정보 보관, 실제 HTTP/DB 호출과 감사 로그
