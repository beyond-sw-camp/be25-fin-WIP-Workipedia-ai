# Tool Calling Guide

> 이슈: #11
>
> 상태: 설계 확정, 구현 중
>
> 최종 수정: 2026-06-14

## 목적

고객사마다 다른 API와 제한된 DB 조회 기능을 코드에 하드코딩하지 않고, BE가 관리하는 Tool 정의를 런타임에 조회해 폴백 오케스트레이터의 D단계에서 실행한다.

AI 서버는 활성·승인 Tool 조회, LLM Tool 선택, 입력 검증, BE 실행 위임, 결과 마스킹과 최종 답변 생성을 담당한다. BE는 Tool 정의와 인증정보 관리, 실제 HTTP/DB 실행, 권한 검증과 감사 로그를 담당한다.

DB Tool은 AI가 SQL을 생성하는 기능이 아니다. 개발자가 등록하고 승인한 SELECT 템플릿에 허용된 파라미터만 바인딩한다.

## 연동 원칙

고객사가 API를 제공하면 API Tool을 우선한다.

```text
LLM이 API Tool과 입력 선택
→ AI가 입력 검증
→ BE가 고객사 API 호출
→ AI가 결과 마스킹
→ LLM이 최종 답변 생성
```

API가 없고 고객사 동의, 네트워크, DB 권한이 확보된 경우에만 DB Query Tool을 사용한다.

```text
LLM이 DB Tool과 입력 선택
→ AI가 입력 검증
→ BE가 사전 등록된 쿼리 템플릿 실행
→ AI가 결과 마스킹
→ LLM이 최종 답변 생성
```

## 구현 경계

### AI 서버

- BE에서 활성화되고 승인된 Tool 목록 조회
- 질문에 맞는 Tool과 입력 인자 선택
- 선택한 `tool_id` 화이트리스트 검증
- JSON Schema 기반 입력 타입·필수값·enum 검증
- 스키마에 없는 입력 인자 차단
- BE 내부 Tool 실행 API 호출
- Tool 결과의 민감정보 마스킹
- Tool 결과에 근거한 최종 답변 생성
- D단계 상태를 오케스트레이터 공통 상태로 변환

### BE 서버

- API Tool 정의 CRUD와 활성 상태 관리
- DB Query Tool 템플릿 검증과 승인 상태 관리
- 인증정보와 datasource 접속정보 보관
- 활성화되고 승인된 Tool만 AI에 반환
- 실제 HTTP API 또는 등록된 DB 쿼리 실행
- 호출자 권한 확인, timeout과 최대 결과 건수 적용
- Tool ID, 호출자, 마스킹된 인자, 결과 건수, 실행 시간과 상태 감사 로그 기록

credential, SQL 원문, Tool 결과 원문은 관리자·LLM·감사 로그에 노출하지 않는다.

## 도메인 구조

```text
app/domain/tool/
├── __init__.py
├── schemas.py
├── client.py
├── selector.py
├── validator.py
├── result_chain.py
└── service.py

app/infra/tool/
├── __init__.py
├── factory.py
├── stub_tool_client.py
└── workipedia_tool_client.py
```

역할:

| 컴포넌트 | 책임 |
|---|---|
| `ToolCallingStep` | 오케스트레이터 D단계 진입점, `ToolService` 위임 |
| `ToolService` | 조회 → 선택 → 검증 → 실행 → 답변 생성 순서 조율 |
| `ToolSelector` | LLM 응답을 검증해 Tool과 입력 선택 |
| `InputValidator` | 활성 Tool 확인과 JSON Schema 입력 검증 |
| `ToolResultChain` | 결과 마스킹과 근거 기반 답변 생성 |
| `ToolClient` | Domain이 의존하는 BE 연동 Protocol |
| `StubToolClient` | BE 미연동 환경에서 빈 Tool 목록 반환 |
| `WorkipediaToolClient` | BE 내부 API를 호출하는 HTTP adapter |

실제 HTTP 통신은 `app/infra/tool/`에 격리하고 Domain에는 `ToolClient` Protocol만 둔다.

## 데이터 흐름

```text
ToolCallingStep.run(query, custom_prompt)
│
├─ ToolClient.get_active_tools()
│  ├─ []                         → NO_RESULT
│  └─ ProviderError              → ERROR
│
├─ ToolSelector.select(query, tools)
│  ├─ None                       → NO_RESULT
│  ├─ ToolSelection              → 계속
│  └─ ProviderError              → ERROR
│
├─ InputValidator.validate(selection, tool_def_map)
│  ├─ 목록에 없는 tool_id        → BLOCKED
│  ├─ 미정의 입력 인자            → BLOCKED
│  ├─ 입력 JSON Schema 위반       → BLOCKED
│  └─ 잘못된 Tool Schema         → ERROR
│
├─ ToolClient.execute(tool_id, inputs)
│  ├─ None / {} / []             → NO_RESULT
│  └─ ProviderError              → ERROR
│
└─ ToolResultChain.generate(query, result, custom_prompt)
   ├─ 마스킹 실패                → BLOCKED
   ├─ INSUFFICIENT_RESULT        → NO_RESULT
   ├─ LLM 호출·파싱 실패         → ERROR
   └─ ANSWER                     → SUCCESS
```

## 도메인 계약

```python
@dataclass
class ToolDefinition:
    tool_id: str
    name: str
    description: str
    parameters_schema: dict


@dataclass
class ToolSelection:
    tool_id: str
    inputs: dict


@dataclass
class ToolExecutionResult:
    tool_id: str
    data: dict | list | None
```

```python
class ToolClient(Protocol):
    def get_active_tools(self) -> list[ToolDefinition]: ...

    def execute(
        self,
        tool_id: str,
        inputs: dict,
    ) -> ToolExecutionResult: ...
```

`get_active_tools()`의 빈 목록은 정상 상태인 “사용 가능한 Tool 없음”을 뜻한다. 통신 실패나 잘못된 응답은 빈 목록으로 숨기지 않고 `ProviderError`를 발생시킨다.

## Tool 정의와 권한

BE의 관리 모델은 다음 정보를 포함한다.

| 필드 | 설명 |
|---|---|
| `name` | LLM에 노출할 고유 Tool 이름 |
| `description` | 사용 조건과 반환 정보 |
| `endpointType` | `HTTP_API` 또는 `DB_QUERY` |
| `endpoint` | API URL 또는 등록된 datasource 식별자 |
| `method` | 허용 HTTP method |
| `parametersSchema` | 허용 입력 JSON Schema |
| `responseSchema` | AI에 반환할 허용 응답 범위 |
| `authType` | API Key, OAuth, Token, None |
| `active` | Tool 활성 여부 |
| `approvalStatus` | 검증·승인 상태 |

AI의 Tool 목록 API에는 `active=true`이면서 `approvalStatus=APPROVED`인 Tool만 반환한다. AI는 이 필터를 중복 구현하지 않지만, LLM이 반환한 `tool_id`가 방금 조회한 목록에 있는지는 반드시 다시 확인한다.

## Tool 선택

`ToolSelector`는 활성 Tool 목록과 질문을 LLM에 전달하고 다음 두 형태만 허용한다.

```json
{"selected": true, "tool_id": "tool_001", "inputs": {"employee_id": "E001"}}
```

```json
{"selected": false}
```

응답은 Pydantic strict 모델로 검증한다.

- `selected`는 boolean이어야 한다.
- `selected=true`이면 비어 있지 않은 문자열 `tool_id`와 object `inputs`가 필요하다.
- `"false"`와 같은 문자열 boolean, 숫자 `tool_id`, 배열 `inputs`는 거부한다.
- JSON 또는 스키마 파싱 실패는 한 번 재시도한다.
- 두 번째 실패는 `ProviderError("llm", ...)`로 처리한다.
- `ToolSelector`는 `RagResult`를 반환하지 않는다.

## 입력 검증

`InputValidator`는 다음 순서로 검증한다.

1. 선택한 `tool_id`가 현재 활성 Tool map에 존재하는지 확인한다.
2. `parametersSchema.properties`에 없는 최상위 입력 키를 거부한다.
3. `jsonschema`로 타입, 필수값, enum과 기타 제약을 검증한다.

스키마에 `additionalProperties: false`가 없더라도 미정의 최상위 인자는 거부한다.

검증 결과:

- LLM이 생성한 입력 위반: `ToolValidationError` → `BLOCKED`
- BE가 반환한 잘못된 JSON Schema: `SchemaError` → `ProviderError` → `ERROR`

## 답변 생성과 출력 마스킹

Tool 결과는 원문 그대로 JSON 직렬화하여 LLM에 전달한다. LLM이 생성한 최종 답변을 사용자에게 반환하기 전에 `masker.mask()`를 적용한다. 마스킹에 실패하면 `BLOCKED`를 반환한다.

최종 답변 LLM은 다음 구조만 반환한다.

```json
{"status": "ANSWER", "answer": "답변"}
```

```json
{"status": "INSUFFICIENT_RESULT"}
```

프롬프트 기본 규칙:

- 제공된 Tool 결과에 있는 정보만 사용한다.
- Tool 결과에 없는 정보는 추측하거나 외부 지식으로 보완하지 않는다.
- 근거가 부족하면 `INSUFFICIENT_RESULT`를 반환한다.
- 기본 보안·근거 규칙은 `custom_prompt`보다 우선한다.

Tool 답변에는 RAG chunk 출처가 없으므로 `GeneratedAnswer.references=[]`를 반환한다.

## BE 내부 API

### 활성 Tool 조회

```http
GET /internal/ai-tools/active
```

```json
[
  {
    "toolId": "tool_001",
    "name": "직원조회",
    "description": "직원 정보를 조회한다",
    "parametersSchema": {
      "type": "object",
      "properties": {
        "employee_id": {"type": "string"}
      },
      "required": ["employee_id"]
    }
  }
]
```

### Tool 실행

```http
POST /internal/ai-tools/{toolId}/execute
```

```json
{"inputs": {"employee_id": "E001"}}
```

```json
{"data": {"name": "홍길동", "department": "개발팀"}}
```

`WorkipediaToolClient`는 timeout, 연결 실패, 4xx/5xx, 잘못된 JSON과 필수 필드 누락을 `ProviderError("tool", ...)`로 변환한다. HTTP timeout은 D단계 전체 timeout보다 짧게 설정한다.

## 클라이언트 선택

환경변수 `TOOL_CLIENT`로 구현체를 선택한다.

| 값 | 구현체 | 동작 |
|---|---|---|
| `stub` | `StubToolClient` | 빈 Tool 목록 반환, D단계 `NO_RESULT` |
| `workipedia` | `WorkipediaToolClient` | BE 내부 API 호출 |

관련 설정:

```text
TOOL_CLIENT=stub
BE_BASE_URL=http://localhost:8080
TOOL_HTTP_TIMEOUT=25
```

## 오케스트레이터 연동

`ToolCallingStep`은 `app/domain/rag/orchestrator.py`에 남고 실제 로직을 `ToolService`에 위임한다.

```python
class ToolCallingStep:
    step_name = "D"
    timeout = STEP_TIMEOUT["D"]

    def __init__(self, service: ToolService | None = None) -> None:
        self._service = service or ToolService(
            client=get_tool_client(),
            selector=ToolSelector(),
            validator=InputValidator(),
            result_chain=ToolResultChain(),
        )

    def run(
        self,
        query: str,
        custom_prompt: str | None,
    ) -> RagResult:
        return self._service.run(query, custom_prompt)
```

A/B/C 단계의 예상 가능한 오류는 다음 검색 단계로 폴백한다. D단계는 마지막 단계이므로 정책을 다음과 같이 구분한다.

- `NO_RESULT`: `NO_RESULT + action="CREATE_TICKET"`
- `BLOCKED`: 즉시 안전 응답
- `ERROR` 또는 `ProviderError`: Tool 인프라 장애로 최종 `ERROR`
- `SUCCESS`: `route="D"`와 답변 반환

## 오류 정책

| 상황 | 상태 |
|---|---|
| 활성 Tool 없음 | `NO_RESULT` |
| LLM이 적합한 Tool을 선택하지 않음 | `NO_RESULT` |
| 목록에 없는 `tool_id` 선택 | `BLOCKED` |
| 미정의 인자 또는 JSON Schema 입력 위반 | `BLOCKED` |
| BE가 잘못된 Tool Schema 반환 | `ERROR` |
| Tool 실행 결과가 `None`, `{}`, `[]` | `NO_RESULT` |
| Tool 결과 마스킹 실패 | `BLOCKED` |
| 결과만으로 답변 불가능 | `NO_RESULT` |
| BE 통신 실패, timeout, 4xx/5xx | `ERROR` |
| LLM 호출 또는 구조화 응답 파싱 실패 | `ERROR` |

## DB Query Tool 제한

- API가 없는 고객사에 대한 예외적 연동 방식으로만 사용
- 개발자 권한에서만 생성·수정
- read-only 계정 사용
- SELECT만 허용
- 단일 쿼리와 파라미터 바인딩만 허용
- 개발자 검증과 승인이 완료된 템플릿만 실행
- AI와 LLM의 임의 SQL 생성·수정 금지
- 허용된 View 또는 컬럼만 조회
- timeout과 최대 결과 건수 적용

## 구현 순서

1. `jsonschema` 의존성과 Tool 설정, `ToolValidationError`를 추가한다.
2. Tool domain schema와 `ToolClient` Protocol을 추가한다.
3. `InputValidator`를 TDD로 구현한다.
4. Pydantic strict 응답 검증을 사용하는 `ToolSelector`를 구현한다.
5. Tool 결과 원문을 LLM에 전달하고 최종 응답에 출력 마스킹을 적용하는 `ToolResultChain`을 구현한다.
6. Stub, Workipedia HTTP adapter와 factory를 구현한다.
7. `ToolService`를 구현해 컴포넌트를 조율한다.
8. `ToolCallingStep` 스텁을 교체하고 D단계 ERROR 정책을 연결한다.
9. Tool 단위 테스트와 전체 회귀 테스트를 실행한다.

작업 단위별 커밋을 유지하되 실제 구현 시 현재 코드와 테스트 상태를 우선한다. 문서의 예시는 복사 대상이 아니라 계약 설명이다.

## 테스트 범위

### `InputValidator`

- 목록에 없는 `tool_id`
- 미정의 입력 인자
- 필수 인자 누락
- 잘못된 입력 타입
- 정상 입력
- 잘못된 JSON Schema

### `ToolSelector`

- Tool 미선택
- 정상 선택
- JSON 파싱 실패 후 재시도 성공
- 두 번 파싱 실패
- LLM provider 오류
- 문자열 boolean
- 잘못된 `tool_id`·`inputs` 타입

### `ToolResultChain`

- 출력 마스킹 실패 → BLOCKED
- `INSUFFICIENT_RESULT`
- 정상 답변과 빈 references
- JSON 파싱 재시도
- 두 번 파싱 실패
- 답변 반환 전 출력 마스킹 적용

### `WorkipediaToolClient`

- 활성 Tool 응답 매핑과 빈 목록
- execute URL, method와 JSON body
- 실행 결과 매핑과 빈 `data`
- 4xx와 5xx
- timeout과 연결 오류
- 잘못된 JSON 또는 필드 누락

HTTP adapter 테스트는 실제 네트워크 대신 `httpx.MockTransport`를 사용한다.

### `ToolService`와 오케스트레이터

- 각 단계의 `NO_RESULT`, `BLOCKED`, `ERROR` 전파
- `ProviderError` 상위 전파
- 정상 end-to-end 조율
- D단계 `NO_RESULT`의 `CREATE_TICKET` 전환
- D단계 `ERROR`와 `ProviderError`의 최종 `ERROR`
- A/B/C ERROR의 기존 폴백 동작 보존

## 완료 기준

- `ToolCallingStep.run()`이 스텁 대신 `ToolService`를 실행한다.
- AI → BE Tool 실행 API → AI 결과 마스킹·해석 왕복이 동작한다.
- 선택 Tool과 입력 로그에 민감정보가 남지 않는다.
- 활성 Tool 없음, 미선택, 잘못된 입력, 빈 결과, 마스킹 실패와 provider 오류가 정책대로 변환된다.
- Tool domain, HTTP adapter, service와 orchestrator 테스트가 통과한다.
- 전체 테스트에서 기존 RAG와 챗봇 동작에 회귀가 없다.
