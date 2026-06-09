# TRD — Workipedia (사내 지식 공유 플랫폼)

> 문서 유형: Technical Requirements Document
> 상태: Draft
> 정본 위치: `docs/reference/trd.md`
> 관련 문서: `docs/reference/service-flow.md`, `docs/reference/prd.md`, `docs/reference/ai-architecture-overview.md`
> 버전: v0.4
> 최종 수정: 2026-06-08

---

## 1. 문서 개요

본 문서는 Workipedia의 기술 아키텍처, 데이터 모델, 외부 의존성, 인터페이스 정의를 기술한다. PRD와 함께 읽어야 한다.

---

## 2. 시스템 아키텍처

### 2.1 컴포넌트 구성 (제안)

```
┌────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│  Frontend  │───▶│   API Gateway/BFF    │───▶│  Backend (REST)  │
│ (React 등) │    │                     │    │   (Spring Boot)  │
└────────────┘    └─────────────────────┘    └──────┬───────────┘
                                                     │
               ┌─────────────────────────────────────┼──────────┐
               ▼                 ▼                   ▼          ▼
         ┌──────────┐    ┌──────────────┐     ┌──────────┐  ┌────────┐
         │   RDB    │    │ Elasticsearch│     │  AI 서버 │  │ Redis  │
         │ (MariaDB)│    │  (BE 전문/   │     │ (FastAPI)│  │        │
         │          │    │  kNN 검색)   │     └────┬─────┘  └────────┘
         └──────────┘    └──────────────┘          │
                                              ┌─────▼──────┐
                                              │  ChromaDB  │
                                              │ (AI RAG    │
                                              │  Vector    │
                                              │  Store)    │
                                              └────────────┘
```

### 2.2 기술 스택 (제안)
| 계층 | 후보 |
|---|---|
| Frontend | React/Vue + TypeScript, TanStack Query, TailwindCSS |
| Backend | Spring Boot 3.x (Java 21) |
| ORM | JPA(Hibernate) |
| RDB | MariaDB/MySQL 계열 |
| BE 검색 엔진 | Elasticsearch 8.15.3 (전문 검색·BE 검색 기능) — ADR 009 참조 |
| AI Vector Store | ChromaDB persistent (RAG·라우팅 후보 검색) |
| 인증 | JWT (Access + Refresh), 비밀번호 BCrypt |
| 세션/임시 메시지 저장 | Redis (Refresh Token, Flash Chat TTL 메시지 저장) — ADR 003 참조 |
| LLM | 고객사 설정에 따라 로컬 또는 클라우드 provider 선택 |
| Embedding | 고객사 설정에 따라 로컬 또는 클라우드 provider 선택 |
| 메시지 브로커 | Kafka (이벤트 기반 알림 등) |
| 실시간 통신 | Spring WebSocket + STOMP (Flash Chat), SSE/폴링 fallback (알림) |
| 배치 | Spring Scheduler/Quartz 우선 |
| 인프라 | Docker, Kubernetes(선택), CI/CD: GitHub Actions |
| 모니터링 | Prometheus + Grafana, 로그: ELK / Loki |

### 2.3 RAG 파이프라인

1. **인덱싱(이벤트 기반 + 일일 정합성 점검)** — KNOIT_006
   - 매뉴얼·워키·수기 지식·승인 지식·라우팅 사례의 생성/수정/삭제 이벤트 수신
   - AI 서버가 매뉴얼, 워키, 수기 지식, 승인된 지식화 문서, 승인된 라우팅 사례를 문서 유형별로 분할
   - 생성된 chunk → `worki_chunks`, `manual_chunks` 등 chunk 테이블에 저장
   - 선택된 Embedding provider로 임베딩 생성 → ChromaDB에 upsert
   - 일일 배치는 누락·실패 데이터 재처리와 RDB/ChromaDB 정합성 점검에 사용

2. **질의 처리(실시간)** — KNOIT_001~003
   - 사용자 질문 → 민감정보 탐지 및 마스킹(KNOIT_007/008)
   - 마스킹된 질문 임베딩 → Vector Store 유사도 검색(top-k)
   - 검색된 chunk + 원본 매뉴얼/워키 메타 → LLM 프롬프트 컨텍스트 구성
   - LLM 응답 생성 + 출처 메타 함께 반환(KNOIT_003)
   - 채팅 메시지 저장(KNOIT_004) → `chatbot_sessions`, `chatbot_messages`

3. **실패 / 불만족 / 요청 전환 흐름** — KNOIT_005
   - 검색 결과 없음, Cross-Encoder 점수 미달, 출처 검증 실패 시 `NO_RESULT` 반환
   - LLM 답변 문자열이 아니라 구조화된 실행 상태로 다음 폴백 단계를 결정
   - 사용자 불만족 피드백 → 워키 질문 등록 흐름으로 분기
   - 실제 처리나 공식 확인이 필요한 경우 → 요청 티켓 생성 흐름으로 분기, 챗봇 입력 내용을 요청 초안으로 전달

4. **지식화 발행과 Vector Store 동기화**
   - TEAM_ADMIN 승인 트랜잭션에서 지식 문서와 `PENDING` 동기화 상태를 RDB에 저장
   - RDB 커밋 후 비동기 작업이 마스킹, 청킹, 임베딩, Vector Store upsert 수행
   - 성공 시 `SYNCED`, 실패 시 `FAILED`와 실패 사유 저장
   - 실패 건은 재시도할 수 있으며 RDB와 Vector Store를 하나의 로컬 트랜잭션으로 묶지 않음

### 2.4 Flash Chat 흐름

1. 사용자가 Flash Chat 화면에 진입하면 현재 활성 메시지 목록을 조회한다.
2. 클라이언트는 STOMP topic `/topic/flash-chat`을 구독한다.
3. 메시지와 답장은 `/app/flash-chat/send`로 전송한다.
4. 서버는 메시지를 Redis에 TTL 600초로 저장하고 구독자에게 브로드캐스트한다.
5. SYSTEM_ADMIN은 `flash_chat_policy`의 TTL, 쿨다운, 금지어를 변경하고 메시지를 강제 삭제할 수 있다.
6. 정책 변경과 강제 삭제는 `admin_logs`에 기록하며, 강제 삭제 시 `/topic/flash-chat`으로 삭제 이벤트를 브로드캐스트한다.

Flash Chat 메시지는 전사 공개 임시 채팅이며, 영구 DB 저장 대상이 아니다.
좋아요 반응(`/app/flash-chat/react`)은 MVP 이후 범위다.

Redis 키 구조:

| 키 | 타입 | 용도 |
|---|---|---|
| `flash-chat:msg:{uuid}` | Hash | userId, nickname, content, replyToId, createdAt, expiresAt 저장. 정책 TTL 적용 |
| `flash-chat:messages` | Sorted Set | member=messageId, score=createdAt epoch(ms)인 활성 메시지 인덱스 |
| `flash-chat:cooldown:{userId}` | String | 사용자별 전송 쿨다운 표시. 쿨다운이 0초면 생성하지 않음 |

---

## 3. 데이터 모델

### 3.1 현재 DB 기준

DB 스키마 정본은 `src/main/resources/db/migration`의 Flyway migration이며, 본 문서는 **현재 repository에 존재하는 migration 전체를 적용한 스키마**를 기준으로 한다.

아직 migration이 없는 기능은 `3.4 추가 예정 테이블/컬럼`에 별도로 둔다.

### 3.2 현재 migration 기준 주요 테이블

| 테이블 | 용도 |
|---|---|
| `users` | 사용자 계정 (사번, 부서, role) |
| `departments` | 부서 마스터 |
| `department_routing_prompts` | 부서별 R&R 프롬프트 |
| `routing_rules` | 키워드 기반 부서 배정 규칙 |
| `worki_questions` | 워키 질문 |
| `worki_answers` | 워키 답변 |
| `reactions` | 좋아요/싫어요 |
| `manuals` | 사내 매뉴얼/규정 |
| `chatbot_sessions` | 챗봇 대화 세션 |
| `chatbot_messages` | 챗봇 메시지(질문/답변 단위) |
| `tickets` | 부서 배정 티켓 |
| `ticket_answers` | 티켓 공식 답변 |
| `ticket_status_logs` | 티켓 상태 변경 이력 |
| `ticket_transfer_requests` | 티켓 이관 요청 및 처리 이력 |
| `ticket_assignments` | 티켓 담당자 배정 이력 |
| `ticket_routing_logs` | 자동 배정 점수와 근거 |
| `knowledge_data` | TEAM_ADMIN이 승인한 티켓 지식 데이터 |
| `user_points` / `point_history` / `points_daily_limit` | 사용자 현재 포인트, 포인트 적립 이력, 일일 적립 한도 |
| `esg_grade` | ESG 점수 기반 등급 기준 |
| `notifications` | 알림 |
| `worki_chunks` | 워키 문장 조각 (검색·인용 단위) |
| `worki_search_logs` | 워키 검색어와 선택한 검색 결과 로그 |
| `manual_chunks` | 매뉴얼 문장 조각 (검색·인용 단위) |
| `manual_versions` | 매뉴얼 버전 이력 |
| `manual_citations` | RAG/답변에서 참조한 매뉴얼 조각 인용 이력 |
| `worki_search_keywords` | 워키 검색 키워드 통계 |
| `flash_chat_policy` | Flash Chat TTL, 쿨다운, 금지어 정책 |
| `ai_tools` | API/DB Query Tool 정의, 입력·응답 스키마와 활성·승인 상태 |
| `admin_logs` | 관리자 작업 로그 |

### 3.3 현재 migration 기준 핵심 컬럼 메모

#### users
- `user_id` BIGINT PK (AUTO_INCREMENT)
- `department_id` BIGINT FK → departments
- `role` VARCHAR(30) CHECK IN ('USER','TEAM_ADMIN','SYSTEM_ADMIN'), 기본 USER
- `employee_id` VARCHAR(100) UNIQUE NOT NULL — 사번
- `email` VARCHAR(255) UNIQUE NOT NULL
- `password` VARCHAR(255) NOT NULL
- `nickname` VARCHAR(100) NOT NULL, 중복 허용
- `status` VARCHAR(20) CHECK IN ('ACTIVE','INACTIVE'), 기본 ACTIVE
- `last_login_at`, 시간컬럼, soft delete 컬럼

#### worki_questions
- `question_id` PK, `author_id` FK, `source_chatbot_message_id` FK NULL, `title`, `content`
- `status` (WAITING / IN_PROGRESS / ANSWERED / TICKETED 등)
- `accepted_answer_id` FK NULL, `view_count`, `modified_source`, 시간컬럼, soft delete 컬럼

#### worki_answers
- `answer_id` PK, `question_id` FK, `author_id` FK
- `ticket_id` FK NULL (티켓 공식 답변에서 생성된 경우)
- `content`, `official` BOOLEAN, `accepted` BOOLEAN, `accepted_at`, `modified_source`, 시간컬럼, soft delete 컬럼

#### reactions
- `reaction_id` PK, `user_id` FK
- `target_type` (WORKI_QUESTION / WORKI_ANSWER)
- `target_id`, `reaction_type` (LIKE / DISLIKE)
- 사용자와 대상 조합은 unique
- `modified_source`, 시간컬럼, soft delete 컬럼

#### tickets
- `ticket_id` PK
- `requester_id` FK → users
- `source_chatbot_message_id` FK → chatbot_messages NULL 허용
- `title`, `content`
- `priority` (MEDIUM / HIGH), 기본 MEDIUM
- `assignee_id` FK → users NULL 허용 (TEAM_ADMIN이 담당 팀원 배정)
- `assigned_department_id` FK → departments NULL 허용
- `routing_confidence_score` DECIMAL(5,2)
- `routing_decision` (AUTO_ASSIGNED / ADMIN_REVIEW / COMMON_QUEUE / NEED_MORE_INFO)
- `status` (RECEIVED / COMMON_QUEUE / ASSIGNED / IN_PROGRESS / COMPLETED / REJECTED / DELETED)
- `completed_at`, 시간컬럼, soft delete 컬럼

#### ticket_answers
- `ticket_answer_id` PK
- `ticket_id` FK → tickets
- `author_id` FK → users
- `content`, 시간컬럼, soft delete 컬럼

#### ticket_status_logs
- `status_log_id` PK
- `ticket_id` FK → tickets
- `changed_by` FK → users NULL 허용
- `previous_status`, `new_status`, `reason`
- 시간컬럼, soft delete 컬럼

#### ticket_assignments
- `assignment_id` PK
- `ticket_id` FK → tickets
- `assignee_id` FK → users
- `assigned_by` FK → users (TEAM_ADMIN 또는 SYSTEM_ADMIN)
- `memo`, 시간컬럼, soft delete 컬럼

#### ticket_routing_logs
- `routing_log_id` PK
- `ticket_id` FK → tickets
- `confidence_score` DECIMAL(5,2)
- `candidate_departments_json` JSON
- `reasons_json` JSON
- `routed_by` FK → users NULL 허용
- `decision` (AUTO_ASSIGNED / ADMIN_REVIEW / COMMON_QUEUE / NEED_MORE_INFO)
- 시간컬럼, soft delete 컬럼

#### knowledge_data
- `knowledge_data_id` PK
- `ticket_id` FK → tickets
- `title`, `content`
- `department_id` FK → departments NULL 허용
- `approved_by` FK → users (TEAM_ADMIN)
- `approved_at`, 시간컬럼, soft delete 컬럼
- 티켓당 하나의 승인 지식만 저장하도록 `ticket_id` UNIQUE

#### ai_tools
- `ai_tool_id` PK
- `name`, `description`, `tool_type` (HTTP_API / DB_QUERY)
- HTTP API: `endpoint_url`, `http_method`
- DB Query: `datasource_key`, `query_template`
- `parameters_schema`, `response_schema`
- `auth_type`, `credential_ref`
- `timeout_ms`, `max_result_count`
- `approval_status` (DRAFT / APPROVED / REJECTED), `is_active`
- `created_by`, `updated_by` FK → users
- 공통 시간컬럼, soft delete, `modified_source`

#### ticket_transfer_requests
- `transfer_request_id` PK
- `ticket_id` FK → tickets
- `from_department_id`, `suggested_department_id` NULL 허용
- `requester_id` FK → users (TEAM_ADMIN)
- `status` (REQUESTED / ASSIGNED_FROM_QUEUE / REJECTED)
- `reason`, 시간컬럼
- 이관 요청이 생성되면 티켓은 `COMMON_QUEUE` 상태로 이동하며, `SYSTEM_ADMIN`이 공통 접수 큐에서 담당 부서를 재배정한다.

#### chatbot_messages
- `message_id` PK, `session_id` FK
- `sender_type` (USER / ASSISTANT / SYSTEM)
- `content`
- `answerable` BOOLEAN NULL
- `next_action` (SHOW_SOURCES / CREATE_WORKI / CREATE_TICKET)
- `references_json` JSON (참조한 매뉴얼/워키 chunk 목록)
- `source_worki_question_id` FK NULL (워키 질문으로 전환된 경우)
- `source_ticket_id` FK NULL (요청 티켓으로 전환된 경우)
- 시간컬럼, soft delete 컬럼

#### worki_chunks / manual_chunks
- `worki_chunk_id` / `manual_chunk_id` PK
- `source_type`, `source_id`, `question_id`, `answer_id` (worki_chunks)
- `manual_id`, `chunk_index` (manual_chunks)
- `content` TEXT
- `embedding_json` JSON NULL

#### admin_logs
- `admin_log_id` PK, `actor_id` (관리자) FK
- `action_type` CHECK IN ('USER_DEACTIVATE','WORKI_READ','WORKI_UPDATE','WORKI_DELETE','MANUAL_UPDATE','MANUAL_DELETE','TICKET_ASSIGN','TICKET_TRANSFER_REQUEST','TICKET_ROUTE_OVERRIDE','COMMON_QUEUE_ASSIGN','KNOWLEDGE_REVIEW','KNOWLEDGE_PUBLISH', ...)
- `target_type`, `target_id`, `description`, `metadata_json`, 시간컬럼, soft delete 컬럼

#### departments
- 현재 migration 기준 컬럼명은 `department_name`
- V5에서 `code`, `description` 컬럼은 제거됨

### 3.4 추가 예정 테이블/컬럼

아래 항목은 PRD/TRD 기능 설계에는 포함되지만, 현재 migration에는 아직 없다. 구현 시 신규 migration으로 추가한다.

| 항목 | 용도 | 예상 migration |
|---|---|---|
| `attachments` | 티켓/요청 사진 첨부 메타데이터 | 신규 migration |
| `ai_prompt_settings` | SYSTEM_ADMIN이 관리하는 챗봇 custom_prompt와 활성 상태 | 신규 migration |
| `manual_knowledge` | SYSTEM_ADMIN 수기 지식과 동기화 상태 | 신규 migration |
| `tool_call_logs` | Tool 호출 감사 및 성공·실패 이력 | 신규 migration |
| `ticket_routing_cases` | TEAM_ADMIN이 승인한 부서 라우팅 검색 사례 | 신규 migration |
| `knowledge_data.sync_status` 등 | ChromaDB 동기화 상태·실패 사유·문서 ID | 신규 migration |

> 상세 컬럼·제약의 최종 정본은 Flyway migration이다.

#### flash_chat_policy

- V12에서 생성된 Flash Chat 운영 정책 단일 행 테이블이다.
- `message_ttl_seconds`: 메시지 보존 시간, 기본 600초
- `send_cooldown_seconds`: 사용자별 전송 쿨다운, 기본 0초
- `banned_words`: 금지어 목록 JSON
- 공통 필드 `created_at`, `updated_at`, `deleted_at`, `is_deleted`, `modified_source`를 사용한다.
- 정책 변경은 `FLASH_CHAT_CONFIG_UPDATE`, 메시지 강제 삭제는 `FLASH_CHAT_MESSAGE_DELETE`로 `admin_logs`에 기록한다.

---

## 4. API 설계 원칙

### 4.1 공통
- REST + JSON
- 인증: `Authorization: Bearer <JWT>`
- 페이지네이션: `?page=&size=&sort=`
- 응답 표준: `{ "data": ..., "error": null, "meta": {...} }`

### 4.2 주요 엔드포인트 (예시)

| Method | Path | 설명 |
|---|---|---|
| POST | `/auth/signup` | 회원가입 |
| POST | `/auth/login` | 로그인 |
| POST | `/auth/logout` | 로그아웃 |
| GET  | `/me` | 내 정보 |
| POST | `/chatbot/sessions` | 세션 생성 |
| POST | `/chatbot/sessions/{id}/messages` | 챗봇 질의 |
| GET  | `/chatbot/sessions/{id}/messages` | 세션 내 메시지 조회 |
| GET  | `/worki/questions` | 질문 목록 (검색·필터·정렬) |
| POST | `/worki/questions` | 질문 등록 |
| PATCH | `/worki/questions/{id}` | 질문 수정 (WAITING 상태만) |
| POST | `/worki/questions/{id}/answers` | 답변 등록 |
| POST | `/worki/answers/{id}/accept` | 답변 채택 |
| POST | `/worki/{target}/{id}/reactions` | 좋아요/싫어요 |
| GET  | `/tickets` | 티켓 목록 (본인/부서) |
| POST | `/tickets` | 요청 티켓 생성 |
| POST | `/attachments` | 이미지 첨부 업로드 |
| GET | `/attachments/{id}` | 첨부 이미지 조회 |
| GET | `/flash-chat/messages` | 활성 Flash Chat 메시지 조회 |
| PATCH | `/tickets/{id}/status` | 상태 변경 |
| PATCH | `/tickets/{id}/assignee` | 팀원 담당자 배정 |
| POST | `/tickets/{id}/transfer-requests` | TEAM_ADMIN 티켓 이관 요청 |
| PATCH | `/admin/common-queue/tickets/{id}/department` | SYSTEM_ADMIN 공통 접수 큐 티켓 부서 재배정 |
| POST | `/tickets/{id}/knowledge-data` | TEAM_ADMIN이 처리 완료 티켓의 지식 데이터를 승인·저장 |
| GET | `/knowledge-data/{id}` | 승인 지식 데이터 조회 |
| GET  | `/manuals` / GET `/manuals/{id}` | 매뉴얼 조회 |
| GET  | `/esg/metrics/me` | 내 ESG 지표 조회 |
| GET  | `/admin/dashboard` | 관리자 대시보드 데이터 |
| DELETE | `/admin/worki/{id}` | 워키 삭제(관리자 전용) |
| GET/POST | `/admin/ai-tools` | API Tool 및 승인된 DB Query Tool 조회·등록 |
| PATCH | `/admin/ai-tools/{id}` | Tool 설정과 활성 상태 변경 |
| POST | `/admin/ai-tools/{id}/test` | 권한과 마스킹을 적용한 Tool 테스트 호출 |
| GET/POST | `/admin/manual-knowledge` | 수기 지식 조회·등록 |
| PATCH/DELETE | `/admin/manual-knowledge/{id}` | 수기 지식 수정·삭제 |
| POST | `/admin/manual-knowledge/{id}/sync` | 실패한 임베딩 동기화 재시도 |

WebSocket/STOMP:

| Type | Path | 설명 |
|---|---|---|
| Connect | `/ws/flash-chat` | STOMP 연결 endpoint (SockJS 지원) |
| Connect | `/ws/flash-chat-native` | Native WebSocket STOMP 연결 endpoint |
| Subscribe | `/topic/flash-chat` | Flash Chat 메시지/삭제 이벤트 수신 |
| Send | `/app/flash-chat/send` | Flash Chat 메시지 전송 |

---

## 5. 보안 요구사항

| 항목 | 요구사항 |
|---|---|
| 비밀번호 | 8자 이상 영문+숫자 / BCrypt 저장 |
| 인증 | JWT(짧은 Access + Refresh), HttpOnly 쿠키 또는 헤더 |
| 권한 검사 | 모든 변경 API에서 USER/TEAM_ADMIN/SYSTEM_ADMIN/부서원 권한 명시 검증 |
| 개인정보 마스킹 | KNOIT_007 — 저장 및 모델 호출 전에 주민번호/연락처/계좌 등 민감정보 마스킹 |
| 개인정보 답변 거부 | KNOIT_008 — LLM 응답 후처리에 개인정보 유출 검사 |
| Flash Chat 임시성 | 메시지는 Redis TTL로 삭제하며 영구 DB에 저장하지 않음 |
| 파일 첨부 | 이미지 MIME/크기 제한, 저장 경로 직접 노출 금지, 고객사별 S3/MinIO adapter 선택 |
| 관리자 추적 | 모든 TEAM_ADMIN/SYSTEM_ADMIN 작업은 `admin_logs`에 기록 |
| 퇴사자 차단 | `users.status = INACTIVE` 사용자는 로그인 거부 |
| 데이터 보존 | 워키 게시글은 USER가 직접 삭제 불가, soft delete 사용 |

---

## 6. 비기능 요구사항(NFR)

| 항목 | 목표 |
|---|---|
| 챗봇 응답 시간 (p95) | 5초 이내 |
| 워키 목록 조회 (p95) | 500ms 이내 |
| 가용성 | 평일 09:00~19:00 사내 SLA 99.5% |
| 임베딩 배치 | 일 1회, 1만 chunk 기준 30분 이내 |
| Flash Chat TTL | 기본 600초 |
| Flash Chat 전송 쿨다운 | 기본 0초(비활성), 관리자 설정 가능 |
| 동시 사용자 | 사내 동시 접속 500명 기준 |
| 로깅 | 마스킹된 챗봇 질의/응답, 관리자 작업, 인증 이벤트 기록 |

---

## 7. 외부 의존성

| 의존성 | 사용 목적 | 위험 / 대응 |
|---|---|---|
| LLM Provider | RAG 답변 생성 | 고객사별 local/cloud 구현체 교체, 장애 시 다음 폴백 경로로 이동 |
| Embedding Provider | 문서·질문 임베딩 | 고객사별 local/cloud 구현체 교체, 동일 벡터 계약 유지 |
| Cross-Encoder Reranker | 검색 후보 재정렬 | 후보별 `candidate_id`, 원본 `score`, `rank` 반환 |
| Object Storage | 이미지 첨부 저장 | 고객사별 S3/MinIO 구현체 교체 |

---

## 8. 운영 / 배포

### 8.1 환경 분리
- `dev` / `staging` / `prod` 3단계
- DB 마이그레이션: Flyway / Liquibase
- 비밀 키: AWS Secrets Manager / HashiCorp Vault

### 8.2 모니터링·알람
- 챗봇 응답 시간, LLM 호출 실패율, 임베딩 배치 성공 여부, 티켓 SLA 초과 건수 등을 대시보드화
- 핵심 지표 임계치 초과 시 운영 채널(Slack 등) 알람

### 8.3 백업
- RDB 일 1회 풀백업 + 시간 단위 증분
- Vector Store: 재구축 가능 구조이므로 백업 우선순위는 낮음 (단, 임베딩 비용 절감 위해 주기적 스냅샷 권장)

---

## 9. 마이그레이션 / 데이터 초기화

- 매뉴얼 초기 데이터 적재: 사내 규정 문서 → 관리자 페이지 일괄 업로드 또는 운영 스크립트
- 짧은 운영 정보: SYSTEM_ADMIN 수기 지식 등록 → 저장 시 Vector Store 자동 동기화
- 부서 마스터 적재: 인사팀 데이터 기준
- 초기 사용자: 사번 기반 일괄 등록 + 첫 로그인 시 비밀번호 설정 흐름

---

## 10. 미해결 기술 이슈

1. 매뉴얼 PDF 등 비정형 문서의 문서 유형별 chunk 크기와 overlap
2. Cross-Encoder 점수 정규화와 RAG `NO_RESULT` 임계값
3. 티켓 라우팅의 1위 최소 점수와 1·2위 최소 점수 차이
4. 워키 답변 우선순위 (정책 미확정 — PRD §7 참조)
5. 챗봇 응답 캐싱 정책 (질문 유사도 기반 캐시 hit 조건)
6. 고객사별 이미지 저장소 설정과 S3/MinIO 운영 정책
7. Flash Chat 메시지 최대 보존 개수
