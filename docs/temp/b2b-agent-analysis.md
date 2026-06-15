# B2B Enterprise AI Agent 분석 보고서
> 레포: https://github.com/rhthrhrl0/b2b-enterprise-ai-agent  
> 목적: Workipedia 적용 아이디어 추출
> 상태: 외부 참고 프로젝트의 기존 ChromaDB 구조를 분석한 과거 자료이며, 현재 Workipedia Vector Store 결정은 Qdrant이다.

---

## 1. 전체 프로젝트 구조

```
b2b-enterprise-ai-agent/
├── app.py                          # Streamlit 메인 엔트리포인트
├── config.py                       # 환경변수 중앙 관리
├── logging_setup.py                # 로깅 설정
├── ui_common.py                    # 공통 UI (세션 상태, 유저 셀렉터)
│
├── agents/
│   └── orchestrator.py             # ★ 핵심: AI 라우팅 오케스트레이터
│
├── llm/
│   └── factory.py                  # LLM/임베딩 팩토리 (OpenAI/Ollama 추상화)
│
├── vector/
│   └── chroma_client.py            # ChromaDB 클라이언트 (벡터 CRUD + 하이브리드 검색)
│
├── services/
│   ├── chunking.py                 # 텍스트 청킹, 컨텍스트 빌더
│   ├── retrieval.py                # BM25 + 벡터 하이브리드 검색 엔진
│   ├── rag_utils.py                # 유사도 필터링 유틸
│   ├── dynamic_tools.py            # ★ DB에서 Tool 동적 생성
│   ├── intent.py                   # 질문 의도 분류 (정규식 기반)
│   ├── internal_handlers.py        # 내부 API 핸들러 (직원/부서 조회)
│   ├── data_services.py            # data_services 테이블 CRUD
│   ├── manual.py                   # manual_manual_inputs 테이블 CRUD
│   ├── tickets.py                  # tickets 테이블 CRUD
│   ├── users.py                    # users 테이블 CRUD
│   └── text_parser.py              # 파일 파싱 (PDF/DOCX/TXT → Document)
│
├── db/
│   ├── connection.py               # MariaDB 연결 관리
│   ├── schema.sql                  # 테이블 스키마
│   └── seed.sql                    # 초기 데이터
│
└── pages/                          # Streamlit 멀티페이지
    ├── 1_채팅.py
    ├── 2_매뉴얼_업로드.py
    ├── 3_수기_정보_관리.py          # 수동 가이드 CRUD + ChromaDB 동기화
    ├── 4_데이터_서비스_관리.py      # API Tool 등록/편집
    ├── 5_티켓_이력_보관소.py        # RESOLVED 티켓 → RAG 이관
    ├── 6_나의_티켓_수신함.py
    └── 7_티켓_답변_처리.py
```

---

## 2. 핵심 파이프라인: A→B→C→D 폴백 체인

> **중요**: LangGraph를 사용하지 않는다. 단순 Python for-loop + if-else로 구현되어 있다.

```
사용자 질문 입력
       │
       ▼
[사전 Intent 분류] intent.py — 정규식 기반
  "몇 명", "인원수", "부서별", "사번" 등 패턴 감지
       │
       ├─ 데이터 조회성 질문 감지 → route_order = [B, A, C]
       └─ 그 외 질문            → route_order = [A, B, C]
       │
       ▼
[Route A] 매뉴얼 RAG
  ChromaDB manual_collection 하이브리드 검색 (BM25 + 벡터)
  → 유사도 필터링 → 컨텍스트 조립 → LLM 호출
  → "확인되지 않습니다" 포함 시 None 반환 (다음 Route로)
       │ 성공 시 AgentResponse(route="A") 반환
       ▼ 실패 시
[Route B] Function Calling (Data Service)
  DB에서 is_active=1인 tool 목록 로드
  → Pydantic 모델 동적 생성 → StructuredTool 생성
  → llm.bind_tools() → LLM이 tool 선택 및 파라미터 결정
  → tool.invoke() → 결과 포함해 LLM 재호출 → 최종 답변
       │ 성공 시 AgentResponse(route="B") 반환
       ▼ 실패 시
[Route C] 티켓 이력 RAG
  ChromaDB ticket_history_collection 하이브리드 검색
  → QA 쌍 컨텍스트 조립 → LLM 호출
  → "이력에서 확인되지 않" 포함 시 None 반환
       │ 성공 시 AgentResponse(route="C") 반환
       ▼ 실패 시
[Route D] 티켓 자동 생성
  담당자 자동 배정 → MariaDB tickets 테이블에 INSERT
  AgentResponse(route="D", ticket_id=...) 반환
       │
       ▼
채팅 화면에 답변 + route 분류 + 출처 + 원문 표시
```

---

## 3. Function Calling 구현 상세

### 핵심 아이디어: DB 주도 동적 Tool 생성

Tool이 코드에 하드코딩되어 있지 않다.  
`data_services` 테이블에 API 명세를 등록하면 런타임에 Tool이 자동 생성된다.

### 기본 등록 Tool 4개 (seed.sql)

| Tool 이름 | 설명 | 엔드포인트 | 파라미터 |
|---|---|---|---|
| `get_employee_info` | 사번/이름/이메일로 임직원 조회 | `internal://employee_lookup` | `keyword: str` |
| `get_department_headcount` | 특정 부서 인원 수 조회 | `internal://department_headcount` | `department: str` |
| `get_total_headcount` | 전체 재직 인원 수 조회 | `internal://total_headcount` | 없음 |
| `get_all_department_headcount` | 전 부서 인원 breakdown | `internal://all_department_headcount` | 없음 |

### Tool 생성 코드 패턴 (`dynamic_tools.py`)

```python
# 1. DB에서 active 서비스 로드
for service in list_data_services(active_only=True):
    schema = service["parameters_schema"]  # JSON 스키마

    # 2. Pydantic 모델 동적 생성
    args_model = _build_args_model(service["name"], schema)

    # 3. StructuredTool로 래핑
    tool = StructuredTool.from_function(
        func=_make_func(service),   # 클로저로 서비스 캡처
        name=service["name"],
        description=service["description"],
        args_schema=args_model,
    )
```

### LLM에 Tool 바인딩 및 2-turn 실행 패턴 (`orchestrator.py`)

```python
# 1단계: LLM이 어떤 tool을 어떤 파라미터로 호출할지 결정
llm_with_tools = self.llm.bind_tools(tools, tool_choice="required")
ai_msg = llm_with_tools.invoke([SystemMessage(DATA_SERVICE_SYSTEM_PROMPT), HumanMessage(question)])

# 2단계: 실제 Tool 실행
for call in ai_msg.tool_calls:
    result = tool_map[call["name"]].invoke(call["args"])
    tool_messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

# 3단계: 결과 포함해 LLM 재호출 → 최종 한국어 답변
final = self.llm.invoke([SystemMessage(...), HumanMessage(question), ai_msg, *tool_messages])
```

### internal:// vs HTTP 분기

```python
if endpoint.startswith("internal://"):
    result = call_internal_handler(endpoint, params)  # 직접 DB 쿼리
else:
    response = requests.get(endpoint, params=params)  # 외부 HTTP API
```

---

## 4. RAG 구현 상세

### 4-1. 문서 처리 파이프라인

```
파일 업로드 (PDF/DOCX/TXT)
  → text_parser.py: 형식별 텍스트 추출 (페이지 번호 메타데이터 보존)
  → chunking.py: clean_text() → 유니코드 정규화
  → RecursiveCharacterTextSplitter
      chunk_size=500, chunk_overlap=150
      separators=["\n\n", "\n", "。", ".", " ", ""]
  → ChromaClient.upsert_document_chunks()
      기존 parent_id 청크 전체 삭제 후 재삽입 (완전 교체 방식)
      chunk_id = f"{parent_id}-chunk-{index}"
```

### 4-2. 두 개의 독립 컬렉션

| 컬렉션 | 내용 | 검색 방식 |
|---|---|---|
| `manual_collection` | 매뉴얼 문서 + 수기 가이드 | BM25 + 벡터 하이브리드 |
| `ticket_history_collection` | 답변 완료된 QA 쌍 | BM25 + 벡터 하이브리드 |

### 4-3. 하이브리드 검색 (BM25 + 벡터, RRF 방식)

```python
# retrieval.py - 역순위 기반 점수 합산
for rank, doc in enumerate(bm25_docs):
    scores[chunk_id] += 0.45 / (rank + 1)   # BM25 가중치

for rank, hit in enumerate(vector_hits):
    scores[hit["id"]] += 0.55 / (rank + 1)  # 벡터 가중치

# 한국어 특화 토크나이저
def korean_tokenize(text: str) -> list[str]:
    return re.findall(r"[가-힣]{2,}|[a-zA-Z0-9]+", text)

# BM25 캐시 무효화: 컬렉션 document count 변화 감지
```

### 4-4. 유사도 이중 필터 (`rag_utils.py`)

```python
# 절대 임계값(0.35) + 상위 점수 대비 상대 비율(72%) 동시 적용
top_score = sorted_hits[0].get("similarity", 0)
cutoff = max(0.35, top_score * 0.72)
# → 상위 1등 점수의 72% 미만인 청크는 컨텍스트에서 제외
```

### 4-5. 컨텍스트 조립 패턴

```
--- 참고 1 (출처: IT 보안정책, 페이지: 3, 분류: IT) ---
{청크 내용}
--- 참고 2 (출처: ...) ---
{청크 내용}
...
[최대 8000자, 초과 시 마지막 청크 "...(이하 생략)" 처리]
```

### 4-6. 티켓→RAG 이관의 트랜잭션 처리

```python
# ChromaDB와 MariaDB를 원자적으로 처리 (롤백 패턴)
with get_connection() as conn:
    try:
        chunk_count = chroma.upsert_ticket_history(...)   # 벡터 DB 먼저 저장
        cursor.execute("UPDATE tickets SET rag_synced = 1 ...")
        if cursor.rowcount == 0:
            chroma.delete_ticket_history(parent_id)       # MariaDB 실패 시 벡터 DB 롤백
            raise ValueError("업데이트 실패")
    except Exception:
        chroma.delete_ticket_history(parent_id)           # 예외 시 벡터 DB 롤백
        raise
```

---

## 5. 프롬프트 엔지니어링 패턴

### RAG 시스템 프롬프트 (환각 방지 제약)
```
당신은 사내 업무 매뉴얼 전문가입니다.
반드시 제공된 [Context]만을 바탕으로 [Question]에 답하세요.
1. [Context]에 명시된 내용만 사용하고, 추측하지 마세요.
2. 관련 내용이 없으면 '매뉴얼에서 확인되지 않습니다'라고만 답하세요.
```

### Tool 선택 가이드 프롬프트
```
tool 선택 가이드:
- 회사 전체/총 직원 수 → get_total_headcount
- 부서별 인원 목록    → get_all_department_headcount
- 특정 부서 인원      → get_department_headcount
- 특정 사람 조회      → get_employee_info
매뉴얼·절차·정책 질문이면 tool을 호출하지 마세요.
```

### Negative Answer 감지 (폴백 트리거)
```python
@staticmethod
def _is_negative_answer(answer: str, negative_phrase="확인되지 않") -> bool:
    return negative_phrase in answer or "알 수 없" in answer or "확인할 수 없" in answer.lower()
```

---

## 6. Workipedia 적용 아이디어

### 즉시 적용 가능

| # | 아이디어 | 설명 |
|---|---|---|
| 1 | **4단계 폴백 라우팅** | 매뉴얼 RAG → 구조화 데이터 → 과거 QA → 티켓 생성 순서로 폴백 |
| 2 | **Negative Answer 감지** | "확인되지 않습니다" 포함 시 자동 다음 단계 — 환각 방지에도 효과적 |
| 3 | **상대적 유사도 컷오프** | `max(0.35, top_score × 0.72)` — 저품질 청크 컨텍스트 오염 방지 |
| 4 | **BM25 + 벡터 하이브리드** | ES의 `multi_match` + `kNN`으로 동일 효과 구현 가능 (이미 ES 보유) |
| 5 | **컨텍스트에 출처 헤더** | 각 청크에 출처/페이지/분류 표시 → 사용자 신뢰도 향상 |
| 6 | **parent_id 기반 청크 교체** | 문서 업데이트 시 기존 청크 전체 삭제 후 재삽입 — 오래된 청크 잔존 방지 |

### 중기 적용 가능

| # | 아이디어 | 설명 |
|---|---|---|
| 7 | **동적 Tool 등록 시스템** | 관리자가 UI에서 API 엔드포인트 + JSON 스키마 등록 → LLM Tool로 자동 변환. 코드 수정 없이 HR/전자결재 등 연동 |
| 8 | **해결 티켓 → 지식베이스 루프** | 답변 완료 티켓을 RAG에 등록 → 유사 질문 자동 답변. 시간이 지날수록 품질 향상 |
| 9 | **의도 분류 사전 필터링** | LLM 호출 전 정규식으로 의도 분류 → 불필요한 RAG 검색 스킵, LLM 호출 절감 |
| 10 | **LLM Provider 추상화** | `get_llm()` 팩토리로 환경변수 하나만 바꾸면 OpenAI ↔ 온프레미스 전환 (보안 요건 대응) |

### 아키텍처 레벨 참고

| # | 원칙 | 내용 |
|---|---|---|
| 11 | **스토리지 이원화 엄격 적용** | RDBMS = 구조화 메타데이터, 벡터DB = 임베딩만. RDBMS에 임베딩 저장 금지 |
| 12 | **청킹 파라미터 환경변수화** | CHUNK_SIZE, CHUNK_OVERLAP, RETRIEVAL_K, MAX_CONTEXT_CHARS 전부 env 분리 |

---

## 7. 기술 스택 요약

| 카테고리 | 기술 | 역할 |
|---|---|---|
| 웹 UI | Streamlit | 멀티페이지 UI, 채팅 |
| AI 프레임워크 | LangChain | Tool 바인딩, 메시지 타입, 텍스트 스플리터 |
| LLM | ChatOpenAI (gpt-4o-mini) | 기본 LLM |
| LLM (로컬 대체) | ChatOllama | OpenAI 대체 온프레미스 |
| 벡터 DB | ChromaDB | 로컬 PersistentClient, 2개 컬렉션 |
| RDBMS | MariaDB + pymysql | 구조화 데이터 |
| BM25 | rank-bm25 | 한국어 키워드 검색 |
| 동적 모델 생성 | Pydantic `create_model()` | Tool args 스키마 런타임 생성 |
| **LangGraph** | **미사용** | **순수 Python 조건문으로 A→B→C→D 구현** |

---

## 9. 레포 자체 디벨롭 방향 (약점 분석)

### 약점 1. Intent 분류가 정규식이라 취약

현재 `intent.py`가 `"몇 명", "인원수", "사번"` 같은 단어 패턴으로만 분기함.
- "우리 팀 인원이 몇이야?" → 감지 못할 수 있음
- "개발팀 헤드카운트 알려줘" (영어 섞임) → 놓침
- B 루트가 먼저여야 하는 질문인데 A로 먼저 가는 케이스 발생

**발전 방향**: 정규식 사전 필터를 없애고 LLM에게 route 선택권을 위임.  
질문 → LLM이 `{route: "B", confidence: 0.9}` 형태로 먼저 판단하게 함.  
비용이 약간 올라가지만 정확도가 크게 향상됨.

---

### 약점 2. Stateless — 멀티턴 대화 없음

매 질문이 완전히 독립적. 사용자 입장에서:
```
유저: "연차 신청 방법 알려줘"
봇:  (답변)
유저: "그럼 반차는?"   ← "반차"가 무엇에 대한 반차인지 모름
봇:  (엉뚱한 답변)
```

**발전 방향**: `orchestrator.run()`에 `chat_history: list[Message]`를 받고,  
RAG 검색 전에 이전 대화를 참조해서 질문을 "완성된 형태"로 재작성하는 단계 추가.  
(Contextualized Query Rewriting)

---

### 약점 3. Tool 체이닝 불가 (멀티홉 추론)

현재 B 루트는 한 번의 Function Calling만 가능. 2단계 추론이 필요한 질문 처리 불가:
```
"영업팀 팀장 김철수 씨의 연락처가 뭐야?"
→ 1단계: get_employee_info("김철수") → 부서/직책 확인
→ 2단계: get_employee_info(사번)    → 연락처 조회
```
현재는 1단계에서 끝남.

**발전 방향**: Tool 실행 결과를 다시 LLM에게 피드백하고, "더 호출할 tool이 있는가?"를 판단하는 루프 구조 추가.  
(ReAct 패턴 — Reasoning + Acting)

---

### 약점 4. RAG 품질 향상 여지

**4-a. Reranking 없음**  
BM25 + 벡터 합산 후 순위가 정해지면 그대로 컨텍스트에 들어감.  
Cross-encoder로 "질문-청크 관련성"을 한 번 더 재순위하면 상위 k개의 품질이 올라감.

**4-b. HyDE 없음** (Hypothetical Document Embeddings)  
- 현재: 질문을 그대로 임베딩해서 검색  
- 개선: "이 질문의 이상적인 답변 문서는 어떻게 생겼을까?"를 LLM이 먼저 가상으로 생성 → 그 가상 문서를 임베딩해서 검색  
- 짧은 질문어보다 긴 문서에 가까운 임베딩이 실제 문서와 더 잘 매칭됨

---

### 약점 5. 피드백 루프 없음

답변 후 사용자가 👍/👎를 줄 수 있는 구조가 없어서 어떤 답변이 좋았는지 쌓이지 않음.  
현재 티켓 이력이 수동 등록이라 관리자 피로도가 높음.

**발전 방향**:
- 👍 받은 답변 → `ticket_history_collection` 자동 후보 등록
- 👎 받은 답변 → route 실패로 기록 → 임계값/가중치 자동 조정 데이터로 활용

---

### 디벨롭 우선순위 요약

| # | 약점 | 발전 방향 | 난이도 |
|---|---|---|---|
| 1 | 정규식 Intent 분류 | LLM 기반 라우터 | 중 |
| 2 | Stateless 대화 | Contextualized Query Rewriting | 중 |
| 3 | 단일 Tool 호출 | ReAct 패턴 (Tool 루프) | 높음 |
| 4-a | Reranking 없음 | Cross-encoder 재순위 | 중 |
| 4-b | 짧은 쿼리 임베딩 약점 | HyDE 적용 | 중 |
| 5 | 피드백 없음 | 👍/👎 기반 자동 지식 축적 | 낮음 |

> 임팩트 큰 것: **멀티턴(2)**과 **ReAct(3)**은 현재 완전히 빠져있는 기능이라 도입 시 사용자 경험이 크게 달라짐. **LLM 라우터(1)**는 코드 변경이 작은 대비 정확도 개선이 뚜렷함.

---

## 8. 핵심 인사이트 요약

1. **LangGraph 없이도 멀티 라우팅이 가능하다** — 단순 for-loop + if-else로 충분
2. **Tool을 DB에서 동적 로드하면** 코드 배포 없이 새로운 데이터 소스 연동 가능
3. **Negative Answer로 폴백 트리거** — LLM이 "모른다"고 답하면 자동으로 다음 단계
4. **BM25 + 벡터 하이브리드**가 순수 벡터 검색보다 한국어에서 성능이 높다 (ES로 대체 가능)
5. **티켓 이력 RAG 루프** — 지식 베이스가 사용될수록 자동으로 성장하는 구조
