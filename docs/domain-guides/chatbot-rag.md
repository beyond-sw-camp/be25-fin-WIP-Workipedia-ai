# Chatbot/RAG Domain Guide

> 문서 유형: Development Guide
> 상태: Draft
> 정본 위치: `docs/domain-guides/chatbot-rag.md`
> 관련 문서: `docs/adr/rag-strategy.md`, `docs/adr/local-llm-security-strategy.md`, `docs/reference/ai-architecture-overview.md`
> 버전: v0.10
> 최종 수정: 2026-06-15

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
- 세션 대화 기록을 활용한 후속 질문 검색어 재작성
- 검색용 `retrieval_query`와 답변 생성용 원본 `query` 분리

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
- 사용자에게 반환하는 LLM 응답에만 마스킹 적용 (입력·Vector Store는 원문)
- 근거 부족 시 그럴듯한 답변 생성 금지
- QLoRA 및 파인튜닝 파이프라인은 사용하지 않는다.

## 민감정보 마스킹

`app/common/masking.py`의 `SensitiveDataMasker`를 사용자에게 반환하는 LLM 응답에 적용한다. BE RDB는 암호화 저장하며, LLM 입력과 Vector Store 저장은 원문을 사용한다.

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
챗봇 경로
ChatbotService
→ orchestrator 실행 (원문 입력)
→ LLM 응답 생성 완료
→ SensitiveDataMasker.mask(answer)
→ MaskingBlockedError → BLOCKED 안전 응답 후 종료
→ 마스킹된 답변 반환
```

호출 서비스 계층이 `MaskingBlockedError`를 처리하며, 마스킹 모듈은 예외를 공통 예외 타입으로 변환해 전달한다.

## 세션 컨텍스트와 후속 질문 검색

BE가 전달한 이전 대화는 답변 생성뿐 아니라 후속 질문의 검색 정확도를 높이는 데 사용한다. AI는 세션을 저장하지 않으며 요청마다 필요한 메시지만 전달받는다.

처리 흐름:

```text
ChatRequest
→ 최근 max_context_messages개 선택
→ contextualize(question, context)
→ retrieval_query 생성
→ A/B/C 검색·reranking과 D Tool 선택에는 retrieval_query 사용
→ 최종 답변 생성에는 question과 context 사용
→ LLM 응답 마스킹 후 반환
```

- `query`는 사용자가 입력한 현재 질문 원문이며 최종 답변 생성에 사용한다.
- `retrieval_query`는 대화 기록을 참고해 독립된 검색 문장으로 재작성한 값이다.
- 세션 컨텍스트가 없거나 `MAX_CONTEXT_MESSAGES=0`이면 LLM을 호출하지 않고 `retrieval_query=query`로 처리한다.
- 컨텍스트는 입력 순서를 유지한 채 마지막 `max_context_messages`개만 선택한다.
- contextualize 응답은 code fence를 제거한 첫 줄만 사용한다. 빈 응답이거나 500자를 초과하면 원본 `query`로 fallback한다.
- contextualize provider 오류나 timeout은 검색 전체를 실패시키지 않는다. 원본 `query`로 계속 진행하고 `step_history` 맨 앞에 `CONTEXT/ERROR`를 기록한다.
- 예상하지 못한 구현 오류는 숨기지 않고 HTTP 500으로 전파한다.

LLM 메시지 구성:

```text
SystemMessage(base_prompt + trusted custom_prompt)
HumanMessage(previous USER content)
AIMessage(previous ASSISTANT content)
...
HumanMessage([Context 또는 Tool Result] + current query)
```

이전 대화는 system prompt보다 우선하지 않는다. `SYSTEM` 역할은 BE 요청에서 허용하지 않고 AI가 직접 생성한다.

관련 설정:

```python
max_context_messages = 10
contextualize_llm_timeout = 25.0
STEP_TIMEOUT["CONTEXT"] = 30.0
```

- `MAX_CONTEXT_MESSAGES`는 0 이상이며 0이면 history와 contextualize를 모두 비활성화한다.
- `CONTEXTUALIZE_LLM_TIMEOUT`은 0초보다 크고 `STEP_TIMEOUT["CONTEXT"]`보다 작아야 한다.
- provider HTTP timeout을 outer `asyncio.wait_for()`보다 짧게 설정해 timeout 후 worker thread에 호출이 남는 시간을 제한한다.

## Chunking 책임

BE는 원문과 문서 메타데이터를 AI 서버에 전달하고, AI 서버가 다음 작업을 담당한다.

```text
문서 파싱
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
| `MANUAL` | `manual_chunks` | 500 | 100 |
| `WORKI` | `worki_chunks` | 300 | 50 |
| `KNOWLEDGE_DATA` | `knowledge_data_chunks` | 400 | 80 |
| `MANUAL_KNOWLEDGE` | `manual_knowledge_chunks` | 400 | 80 |

인덱싱 요청:

```text
POST /api/v1/documents/ingest
Content-Type: multipart/form-data

source_id: positive int
source_type: MANUAL | WORKI | KNOWLEDGE_DATA | MANUAL_KNOWLEDGE
title: non-empty string
file: pdf | docx | txt
```

AI 서버는 업로드 파일을 파싱한 뒤 인덱싱한다. 지원하지 않는 파일 형식은 `415`, 파일 파싱 실패는 `422`로 처리한다.

재인덱싱은 임베딩 성공 후 `doc_id={source_type}:{source_id}`인 기존 point를 삭제하고 새 chunk를 upsert한다. 임베딩 실패 시 기존 point를 유지한다.

삭제 요청:

```text
DELETE /api/v1/documents/{source_id}?source_type=MANUAL
```

논리 chunk ID는 `{source_type}:{source_id}:{chunk_index}`이며 Qdrant point ID는 deterministic UUID다.

Embedding provider별 collection vector size:

| provider | 모델 | vector size |
|---|---|---:|
| `local` | `bge-m3` | 1024 |
| `openai` | `text-embedding-3-small` | 1536 |
| `google` | `text-embedding-004` | 768 |

provider를 변경하면서 기존 collection을 재사용하면 차원 불일치가 발생할 수 있으므로 신규 collection 생성과 재색인이 필요하다.

## Retrieval과 Reranking

검색은 후보 폭과 최종 반환 수를 분리한다.

```python
RETRIEVAL_TOP_K = 50
RERANK_TOP_K = 5
```

처리 흐름:

```text
질문 임베딩
-> Qdrant vector search
-> RagCandidate 목록
-> Cross-Encoder reranking
-> RerankedCandidate 목록
```

`RagCandidate`는 Qdrant 원본 점수와 본문, metadata를 유지한다.

```python
@dataclass
class RagCandidate:
    candidate_id: str
    text: str
    score: float
    metadata: dict
```

`RerankedCandidate`는 후속 답변 생성에서 재조회하지 않도록 본문과 출처를 유지하고, vector search 점수와 Cross-Encoder 점수를 분리한다.

```python
@dataclass
class RerankedCandidate:
    candidate_id: str
    text: str
    score: float
    rank: int
    metadata: dict
    retrieval_score: float
```

- `score`: Cross-Encoder 원본 점수
- `retrieval_score`: Qdrant 원본 점수
- `rank`: Cross-Encoder 점수 내림차순의 1-based 순위
- 두 점수는 정규화 전 `0~1` 범위라고 가정하지 않는다.
- 검색 결과가 없거나 `top_k <= 0`이면 빈 목록을 반환한다.
- C단계는 `KNOWLEDGE_DATA`와 `MANUAL_KNOWLEDGE`를 각각 검색한 뒤 후보를 합쳐 한 번만 reranking한다.

Cross-Encoder는 import 시 즉시 생성하지 않는다. `@lru_cache(maxsize=1)`가 적용된 `get_reranker()`로 프로세스당 한 번 생성하고, FastAPI lifespan에서 호출해 서버 기동 시 preload한다. Uvicorn worker가 여러 개면 worker마다 모델 인스턴스가 하나씩 생성된다.

예외 계약:

| 상황 | 처리 |
|---|---|
| 질의 임베딩 실패 | `ProviderError("embedding", ...)` |
| Qdrant 연결 실패 또는 collection 미존재 | `ProviderError("qdrant", ...)` |
| Cross-Encoder 로드 또는 predict 실패 | `ProviderError("cross-encoder", ...)` |
| 검색 결과 0건 | 빈 목록, `NO_RESULT` 판정은 답변 생성 단계 |

조회 시 없는 collection을 자동 생성하지 않는다. collection 생성은 인덱싱 `upsert()` 경로에서만 수행한다.

## 답변 생성과 Negative Answer

`RagChain.generate()`는 질문과 reranking된 후보를 받아 구조화된 답변을 생성한다.

```text
query + RerankedCandidate 목록
-> 최고 점수 임계값 검사
-> system prompt + context 구성
-> LLM 호출
-> JSON 파싱과 스키마 검증
-> 인용 ID 검증
-> RagResult 반환
```

내부 도메인 계약:

```python
class RagStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RESULT = "NO_RESULT"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"

@dataclass
class GeneratedAnswer:
    answer: str
    references: list[RerankedCandidate]

@dataclass
class RagResult:
    status: RagStatus
    answer: GeneratedAnswer | None = None
    error_message: str | None = None
```

LLM은 다음 두 형식 중 하나인 JSON만 반환한다.

```json
{"status":"ANSWER","answer":"답변 텍스트","cited_ids":["MANUAL:1:0"]}
```

```json
{"status":"INSUFFICIENT_CONTEXT","answer":null,"cited_ids":[]}
```

현재 `langchain_community.ChatOllama` 호환성을 위해 `with_structured_output()`을 사용하지 않는다. `invoke()` 응답의 `content`가 문자열 또는 content block 목록인 경우를 모두 처리하고, JSON code fence를 제거한 뒤 `json.loads()`와 Pydantic 모델로 검증한다.

프롬프트 기본 규칙:

- `[Context]`의 내용만 사용하고 외부 지식이나 추측을 사용하지 않는다.
- 근거가 부족하면 `INSUFFICIENT_CONTEXT`를 반환한다.
- 답변에 사용한 모든 chunk ID를 `cited_ids`에 포함한다.
- 한국어로 간결하게 답한다.
- SYSTEM_ADMIN의 `custom_prompt`는 기본 규칙 뒤에 추가하며, 충돌하면 기본 규칙을 우선한다.

다음 조건 중 하나면 `NO_RESULT`다.

1. 검색 후보가 없다.
2. 1위 Cross-Encoder 원본 점수가 `RERANK_SCORE_THRESHOLD` 미만이다.
3. LLM이 `INSUFFICIENT_CONTEXT`를 반환한다.
4. `cited_ids`가 비어 있다.
5. `cited_ids`에 검색 후보에 없는 ID가 포함되어 있다.

유효한 인용 ID만 `references`로 변환하며, 중복 ID는 최초 등장 순서를 유지해 제거한다. 현재 `RERANK_SCORE_THRESHOLD=0.0`은 `bongsoo/kpf-cross-encoder-v1`의 raw logit 기준 임시값이며 평가셋 확보 후 조정한다.

오류와 재시도 책임:

- 네트워크/API 오류는 infra provider 계층의 재시도를 거친 `ProviderError`로 전달되므로 `RagChain`은 즉시 `ERROR`를 반환한다.
- JSON 파싱 또는 응답 스키마 검증 실패는 `RagChain`에서 1회만 다시 호출하고, 다시 실패하면 `ERROR`를 반환한다.
- `NO_RESULT`와 재시도 불가능한 `ERROR`는 다음 폴백 단계로 이동한다.
- `BLOCKED`는 민감정보 마스킹 또는 보안 정책 실패이며 안전 응답 후 종료한다.

`RagResult`는 AI 내부 계약이다. 외부 API의 `{status, answer, references}` 형태로 평탄화하고 reranking 진단 정보를 포함할지는 후속 오케스트레이터 또는 ChatbotService가 담당한다.

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
- D단계 `NO_RESULT`는 최종 전환 액션으로 처리하고, `ERROR`는 일시적 장애 응답으로 구분한다.

### 오케스트레이터 계약

`RagOrchestrator`는 LangGraph 대신 `StepRunner` 목록을 명시적인 for-loop로 순회한다.

| 단계 클래스 | 단계 | 처리 |
|---|---|---|
| `ManualRagStep` | A | `manual_chunks` 검색, reranking, 답변 생성 |
| `WorkiRagStep` | B | `worki_chunks` 검색, reranking, 답변 생성 |
| `KnowledgeRagStep` | C | 승인 지식과 수기 지식 후보를 합쳐 통합 reranking 후 답변 생성 |
| `ToolCallingStep` | D | `ToolService`에 활성 Tool 조회·선택·검증·실행·결과 해석을 위임 |

각 단계는 다음 인터페이스를 제공한다.

```python
class StepRunner(Protocol):
    step_name: str
    timeout: float

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list[SessionMessage],
    ) -> RagResult: ...
```

오케스트레이터 결과:

```python
@dataclass
class StepRecord:
    step: str
    status: RagStatus
    error_message: str | None = None

@dataclass
class OrchestratorResult:
    status: RagStatus
    answer: GeneratedAnswer | None = None
    route: str | None = None
    step_history: list[StepRecord] = field(default_factory=list)
    action: str | None = None
```

실행 규칙:

- `ChatbotService`가 오케스트레이터 실행 후 LLM 응답에 마스킹을 적용하며 실패하면 `BLOCKED`로 즉시 종료한다.
- A/B/C 검색과 reranking, D단계 Tool 선택은 `retrieval_query`를 사용한다.
- RAG 및 Tool 최종 답변 생성은 `query`와 `session_context` 원문을 사용한다.
- `SUCCESS`는 성공 단계의 `route`와 답변을 즉시 반환한다.
- A/B/C의 `NO_RESULT`, 단계가 반환한 `ERROR`, 예상 가능한 `ProviderError`는 다음 단계로 이동한다.
- 단계가 `BLOCKED`를 반환하면 다음 단계를 실행하지 않는다.
- 마지막 D단계의 `ERROR`와 `ProviderError`는 Tool 인프라 장애로 최종 `ERROR`를 반환한다.
- D단계의 `NO_RESULT`는 모든 단계 소진 후 `action="CREATE_TICKET"`으로 전환한다.
- 모든 단계가 실패하면 `NO_RESULT`와 `action="CREATE_TICKET"`을 반환한다.
- 예상하지 못한 구현 예외는 잡지 않고 전파해 HTTP 500으로 처리한다.
- 단, `provider_call()` 블록 내부의 모든 예외는 현재 공통 정책에 따라 `ProviderError`로 변환된다.

현재 단계 timeout은 CONTEXT `30초`, A/B/C/D 각 `120초`다. `asyncio.wait_for(asyncio.to_thread(...))`는 대기만 중단하고 thread를 종료하지 못하므로 timeout 발생 시 다음 단계를 실행하지 않고 `ERROR`를 즉시 반환한다. provider HTTP timeout은 각 단계 timeout보다 짧게 설정한다.

### 챗봇 AI API 계약

AI 서버의 내부 추론 endpoint는 `POST /api/v1/chat`이다. 세션과 메시지 저장은 BE가 담당하고, AI endpoint는 질문 한 건에 대한 답변·출처·전환 액션을 반환한다.

```python
class SessionMessage(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    message_id: int = Field(gt=0)
    sender_type: Literal["USER", "ASSISTANT"]
    content: str = Field(min_length=1, max_length=4000)

class ChatRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    question: str = Field(min_length=1, max_length=2000)
    custom_prompt: str | None = Field(default=None, max_length=4000)
    session_context: list[SessionMessage] = Field(default_factory=list)

class SourceItem(BaseModel):
    candidate_id: str
    source_type: str
    source_id: str
    chunk_index: int | None = None
    title: str
    score: float
    link: str | None = None

class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    route: str | None = None
    action: str | None = None
    step_history: list[StepHistoryItem]
```

- JSON 요청은 camelCase를 사용하며 Pydantic 내부 필드는 snake_case로 유지한다.
- BE는 `sessionContext`를 `messageId` 오름차순으로 전달하고 현재 `question`은 중복 포함하지 않는다.
- `senderType=SYSTEM`, 공백 질문, 공백 메시지 내용은 `422`다.
- `customPrompt`는 일반 사용자가 직접 작성하는 값이 아니라 신뢰된 BE가 활성 SYSTEM_ADMIN 설정을 전달하는 내부 계약이다.
- 실제 검색에 전달하지 않는 `top_k`도 요청에서 받지 않는다.
- 출처의 `source_type`, `source_id`, `chunk_index`는 Qdrant metadata를 정본으로 사용하고 `candidate_id` 파싱은 fallback으로만 사용한다. metadata 값이 변환 불가이거나 음수이면 `candidate_id` 파싱으로 재시도하고, 둘 다 실패하면 `null`을 반환한다.
- AI는 인용된 chunk 식별 정보만 반환한다. `manual_citations` 저장, 답변 단위 중복 방지와 FAQ 인기 매뉴얼 캐시 무효화는 BE가 담당한다.
- 출처 식별값이 없으면 빈 출처를 반환하지 않고 오류로 처리한다.
- `BLOCKED`는 고정 안전 응답, `NO_RESULT + CREATE_TICKET`은 티켓 전환 안내를 반환한다.
- `ERROR`는 근거 없음으로 위장하지 않고 일시적 오류와 재시도를 안내하는 별도 응답으로 변환한다.
- contextualize의 예상 가능한 실패는 원본 질문 fallback 후 `CONTEXT/ERROR` 이력을 포함한 정상 처리로 이어진다.

## 완료 기준

- 질문을 입력하면 챗봇 메시지가 저장된다.
- 근거가 있으면 매뉴얼/워키 출처와 함께 답변한다.
- 근거가 없으면 요청 티켓 전환 액션을 반환한다.
- `references`에 문서 ID, chunk ID, 제목, 링크가 남는다.
- 오래된 출처는 최신성 경고와 함께 표시된다.
- 지원 provider가 동일한 domain 응답 계약을 제공한다.

## 현재 구현 상태

- 파일 업로드 기반 문서 인덱싱·삭제 API와 Qdrant adapter가 구현되어 있다.
- provider enum은 `local`, `openai`, `google`이며 provider별 vector size가 구현되어 있다.
- source type별 최신 청킹값은 `500/100`, `300/50`, `400/80`, `400/80`이다.
- `RagCandidate`, `RerankedCandidate`, `CrossEncoderReranker`, 캐시 팩토리와 관련 단위 테스트가 구현되어 있다.
- Qdrant 조회 시 collection 자동 생성 제거와 회귀 테스트가 구현되어 있다.
- `RagRetriever`, `RagService`, FastAPI lifespan preload 연결이 구현되어 있다.
- `RagChain`, 구조화 답변 스키마, 기본/custom prompt, 인용 검증과 관련 단위 테스트가 구현되어 있다.
- LLM 파싱 실패 1회 재시도와 provider 오류의 즉시 `ERROR` 변환이 구현되어 있다.
- `RagOrchestrator`, `ChatbotService`, `/api/v1/chat` 연결과 endpoint 상태 변환이 구현되어 있다.
- `SourceItem.chunk_index` 응답과 Qdrant metadata 우선·`candidate_id` fallback 변환이 구현되어 BE의 매뉴얼 인용 이력 저장과 연동할 수 있다.
- 세션 컨텍스트 요청 계약, history-aware retrieval query 분리와 contextualize timeout 설계가 확정되어 구현 중이다.
- D단계 Tool Calling 설계와 구현 계획은 `docs/domain-guides/tool-integration.md`에 통합되어 있다. Tool domain 컴포넌트는 구현 중이며 `ToolCallingStep` 연결과 BE HTTP adapter는 남아 있다.
- 실제 Qdrant 통합 테스트, `doc_id` payload index, scroll pagination은 남아 있다.
- 실제 Ollama 통합 테스트와 평가셋 기반 reranker 임계값 보정은 남아 있다.

## 논의 필요 사항

- seed 문서 개수와 내용
- Cross-Encoder 점수 정규화와 `NO_RESULT` 임계값
- embedding 모델 변경 시 collection 재색인 절차
- Qdrant payload index와 통합 테스트 범위
- provider별 contextualize HTTP timeout 동작의 실제 통합 검증
- `BLOCKED`와 `ERROR` 사용자 안내 문구
