# ADR - Customer-specific Deployment and Data Security

> 상태: Accepted  
> 최종 수정: 2026-06-12

## Context

고객사마다 내부망 규제, 클라우드 사용 가능 여부, 저장소 정책이 다르다. A사는 로컬 인프라를 요구할 수 있고 B사는 클라우드 서비스를 선택할 수 있으므로 배포 방식을 코드에 고정하면 고객사별 분기가 누적된다.

## Decision

배포 차이는 provider와 adapter 구현체로 격리한다.

```text
AI Core
├─ LlmProvider
│  ├─ LocalLlmProvider
│  └─ CloudLlmProvider
├─ EmbeddingProvider
│  ├─ LocalEmbeddingProvider
│  └─ CloudEmbeddingProvider
└─ ObjectStorage (BE 소유)
   ├─ S3ObjectStorage
   └─ MinioObjectStorage
```

- 고객사 A는 로컬 LLM/Embedding과 MinIO를 사용할 수 있다.
- 고객사 B는 클라우드 LLM/Embedding과 S3를 사용할 수 있다.
- AI의 RAG, Tool, 라우팅 코드는 구체 provider를 직접 참조하지 않는다.
- 하나의 서버가 tenant별로 provider를 런타임 전환하지 않는다.
- 고객사마다 별도 배포하고 환경변수 또는 배포 프로파일로 구현체를 선택한다.

예:

```text
A사: LLM_PROVIDER=local, EMBEDDING_PROVIDER=local, OBJECT_STORAGE=minio
B사: LLM_PROVIDER=fallback, EMBEDDING_PROVIDER=openai, OBJECT_STORAGE=s3
```

## Sensitive Data

민감정보 보호는 BE RDB 암호화와 AI 서버 응답 마스킹으로 처리한다.

기본 정책:

- BE RDB는 암호화 저장하며 읽을 때만 복호화한다.
- AI 서버는 사용자에게 반환하는 LLM 응답에만 마스킹을 적용한다. LLM 입력과 Vector Store 저장은 원문을 사용한다.
- 주민등록번호와 카드번호는 항상 유형 토큰으로 치환한다. 예: `900101-1234567` → `[주민번호]`
- 전화번호와 이메일은 설정(`MASKING_PHONE_ENABLED`, `MASKING_EMAIL_ENABLED`)에 따라 선택적으로 마스킹한다.
- 계좌번호는 오탐 정책 확정 전까지 자동 마스킹 대상에 포함하지 않는다.
- 마스킹 처리 실패 시 `BLOCKED`로 처리하고 응답을 중단한다.
- 탐지된 민감정보 값은 로그에 남기지 않는다. 적용 여부와 토큰 유형만 기록할 수 있다.

구현 상세와 설정값은 `docs/domain-guides/chatbot-rag.md`의 `민감정보 마스킹` 절을 따른다.

## Image Storage

이미지 첨부 저장은 BE가 `ObjectStorage` 인터페이스로 추상화한다.

| 고객사 유형 | 구현 예 |
|---|---|
| 클라우드형 | AWS S3 |
| 로컬/온프레미스형 | MinIO |

AI는 저장소 위치를 알지 않고, BE가 전달한 파일 식별자 또는 제한된 접근 URL만 사용한다.

## Remaining Decisions

- 이미지 OCR 수행 전 추가 마스킹이 필요한지
