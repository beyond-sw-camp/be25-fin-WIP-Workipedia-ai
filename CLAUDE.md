# Workipedia AI

Workipedia의 RAG 챗봇, Tool Calling, 티켓 부서 라우팅을 담당하는 Python AI 서버다.

## Tech Stack

- Python, FastAPI, Uvicorn
- LangChain
- ChromaDB
- Sentence Transformers Cross-Encoder
- Ollama / OpenAI provider adapter
- PyPDF, python-docx

## Package Structure

```text
app/
├── api/v1/                 # FastAPI endpoint와 router
├── common/                 # 공통 응답, 예외, utility
├── core/                   # 환경설정, 로깅, 보안
├── domain/
│   ├── chatbot/            # 챗봇 요청/응답
│   ├── document/           # 문서 파싱, 청킹, 인덱싱
│   └── rag/                # 검색, reranking, 답변, 폴백 orchestration
└── infra/
    ├── embedding/          # local/cloud embedding adapter
    ├── llm/                # local/cloud LLM adapter
    └── vector_store/       # Vector Store adapter
```

## Key Docs

| 목적 | 경로 |
|---|---|
| AI 전체 구조 | `docs/reference/ai-architecture-overview.md` |
| 제품 요구사항 | `docs/reference/prd.md` |
| 기술 요구사항 | `docs/reference/trd.md` |
| 서비스 흐름 | `docs/reference/service-flow.md` |
| RAG 전략 | `docs/adr/rag-strategy.md` |
| 고객사별 배포·보안 | `docs/adr/deployment-and-data-security.md` |
| 검색 전략 | `docs/adr/search-strategy.md` |
| RAG 구현 | `docs/domain-guides/chatbot-rag.md` |
| 부서 R&R 프롬프트 | `docs/domain-guides/department-routing-prompt.md` |
| Tool Calling | `docs/domain-guides/tool-integration.md` |
| 티켓 부서 라우팅 | `docs/domain-guides/ticket-routing-ai.md` |
| 수기 지식 | `docs/domain-guides/manual-knowledge.md` |
| 참고 레포 분석 | `docs/temp/b2b-agent-analysis.md` |

## Architecture Contract

### 고객사별 배포

- 고객사마다 서버를 별도로 배포한다.
- 로컬/클라우드 LLM과 Embedding 차이는 provider interface와 환경설정으로 분리한다.
- 하나의 서버에서 tenant별 provider를 런타임 변경하지 않는다.
- 민감정보는 저장과 모델 호출 전에 마스킹하며 원문은 보관하지 않는다.
- QLoRA와 LangGraph는 사용하지 않는다.

### A→B→C→D Pipeline

```text
A. 매뉴얼/워키 RAG
→ B. 등록된 Tool 호출
→ C. 해결된 티켓 이력 RAG
→ D. 요청 티켓 생성
```

- LangGraph 대신 명시적인 Python for-loop와 if-else로 구현한다.
- 단계별 결과는 `SUCCESS`, `NO_RESULT`, `ERROR`, `BLOCKED`로 통일한다.
- `SUCCESS`면 즉시 반환한다.
- `NO_RESULT`와 재시도 불가능한 `ERROR`는 다음 단계로 이동한다.
- `BLOCKED`는 민감정보·권한·입력 검증 실패이므로 안전 응답 후 종료한다.
- LLM 답변 문자열에서 특정 문구를 찾아 폴백 여부를 결정하지 않는다.

### Prompt

- `base_prompt`: 출처, 거절, 전환, 보안 등 핵심 규칙. 코드 또는 배포 설정으로 고정한다.
- `custom_prompt`: 고객사별 답변 지침. SYSTEM_ADMIN이 내용과 활성 상태를 관리한다.
- 최종 프롬프트는 활성화된 경우에만 `base_prompt + custom_prompt`로 구성한다.
- 부서별 R&R 프롬프트는 SYSTEM_ADMIN이 관리하며 티켓 담당 부서 추천에 사용한다.

### RAG

- AI 서버가 문서 파싱, 민감정보 마스킹, 청킹, 임베딩, Vector Store 저장을 담당한다.
- 대상은 매뉴얼, 워키, 수기 지식, 승인된 지식화 문서, 승인된 라우팅 사례다.
- Vector Search로 후보를 넓게 검색한 뒤 로컬 Cross-Encoder로 재정렬한다.
- Reranker는 후보별 `candidate_id`, 원본 `score`, `rank`를 반환한다.
- 점수는 모델별 원본 값이며, 정규화 전에는 `0~1` 범위라고 가정하지 않는다.
- 검색 결과 없음, reranker 점수 미달, 출처 없음·불일치는 `NO_RESULT`다.
- 출처 없는 답변과 검색 근거 밖의 답변 생성을 허용하지 않는다.

### Tool Calling

- 사용자·관리자 UI에서는 `Tool 관리`, 기술 문서에서는 `Tool Calling`을 기본 명칭으로 사용한다.
- SYSTEM_ADMIN은 HTTP API Tool을 등록하고 활성화한다.
- API가 없는 고객사는 개발자가 검증한 DB Query Tool을 사용할 수 있다.
- LLM은 승인·활성화된 Tool과 입력 인자만 선택한다.
- LLM이 SQL을 생성하거나 수정하지 않는다.
- BE가 Tool 정의, 인증정보 참조, 실제 HTTP/DB 실행, 결과 마스킹과 감사 로그를 담당한다.
- AI 서버는 Tool 선택, 입력 스키마 검증, 결과 해석과 답변 생성을 담당한다.

### Ticket Department Routing

```text
티켓 내용
→ 부서 R&R + 승인된 처리 사례 Vector Search
→ 부서 후보 Top 3
→ Cross-Encoder reranking
→ 점수와 1·2위 차이 검증
→ 담당 부서 추천 또는 공통 접수 큐
```

- 라우팅 판단 결과에는 `top_score`와 1·2위 간 `score_margin`을 포함한다.
- AI는 개인이 아닌 담당 부서까지만 추천한다.
- 부서 내부 팀원 배정은 TEAM_ADMIN이 수행한다.
- 최종 처리 완료 후 TEAM_ADMIN이 승인한 사례만 Vector Store에 추가한다.
- 이관 요청만으로 사례를 확정하지 않는다.
- 임베딩 모델과 Cross-Encoder를 온라인 재학습하지 않는다.
- 부서 벡터를 직접 이동시키지 않고 검색 근거 데이터만 갱신한다.

### Knowledge Sync

- 지식화 승인은 BE의 RDB에 먼저 커밋한다.
- AI 인덱싱 작업은 마스킹, 청킹, 임베딩, Vector Store upsert를 수행한다.
- 동기화 상태는 `PENDING`, `SYNCED`, `FAILED`로 관리한다.
- RDB와 Vector Store를 하나의 로컬 트랜잭션으로 묶지 않는다.
- 실패 작업은 재시도 가능해야 한다.

## Repository Boundaries

### AI

- 문서 파싱, 청킹, 임베딩, 검색
- Cross-Encoder reranking
- 근거 기반 답변 생성
- Tool 선택과 결과 해석
- A→B→C→D 폴백 orchestration
- 부서 후보 검색과 추천
- 민감정보 탐지·마스킹

### BE

- 인증과 사용자 권한
- `custom_prompt`, 부서 R&R, Tool, 수기 지식 CRUD
- API 인증정보와 DB datasource 관리
- 실제 HTTP API 및 DB Query 실행
- 티켓 생성·배정·이관·지식화 상태 저장
- Vector Store 동기화 상태와 감사 로그
- 이미지 저장소 S3/MinIO 추상화

## Current State

- FastAPI 기본 서버와 `/api/v1` router가 구성되어 있다.
- chatbot, documents, embeddings endpoint가 존재한다.
- Ollama/OpenAI LLM·Embedding adapter가 존재한다.
- ChromaDB adapter와 기본 문서 chunker가 존재한다.
- Cross-Encoder 설정은 존재하지만 실제 reranking 연결은 확인하며 구현한다.
- A→B→C→D orchestrator와 Tool Calling, 티켓 부서 라우팅은 구현이 필요하다.

## Development Commands

```bash
make install
make dev
make run
```

## Development Rules

- 구체 provider를 domain 코드에서 직접 참조하지 않는다.
- API endpoint는 `app/api/v1/`, 업무 로직은 `app/domain/`, 외부 구현체는 `app/infra/`에 둔다.
- 코드 변경 시 관련 domain guide와 TRD를 함께 갱신한다.
- 민감정보, API key, DB 접속정보를 로그에 기록하지 않는다.
- `.env`는 커밋하지 않는다.
- `docs/temp/`는 참고 자료이며 구현 계약의 근거로 사용하지 않는다.
