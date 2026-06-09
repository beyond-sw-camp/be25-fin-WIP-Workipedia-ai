# ADR - Customer-specific Deployment and Data Security

> 상태: Accepted  
> 최종 수정: 2026-06-09

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
B사: LLM_PROVIDER=cloud, EMBEDDING_PROVIDER=cloud, OBJECT_STORAGE=s3
```

## Sensitive Data

민감정보는 원천 데이터 전체를 차단하는 방식이 아니라 입력과 수집 데이터에서 탐지 후 마스킹한다.

처리 순서:

```text
입력/수집
→ 민감정보 탐지
→ 유형별 마스킹
→ 마스킹 결과 검증
→ DB 저장
→ RAG 인덱싱 또는 LLM 호출
```

기본 정책:

- 주민등록번호, 계좌번호, 개인 연락처 등은 유형을 식별할 수 있는 토큰으로 치환한다.
- 예: `900101-1234567` → `[RESIDENT_ID]`
- 마스킹 전 원문은 기본적으로 DB와 로그에 저장하지 않는다.
- 클라우드 provider에는 마스킹된 데이터만 전달한다.
- 마스킹 실패 시 저장 또는 모델 호출을 중단할 수 있어야 한다.

## Image Storage

이미지 첨부 저장은 BE가 `ObjectStorage` 인터페이스로 추상화한다.

| 고객사 유형 | 구현 예 |
|---|---|
| 클라우드형 | AWS S3 |
| 로컬/온프레미스형 | MinIO |

AI는 저장소 위치를 알지 않고, BE가 전달한 파일 식별자 또는 제한된 접근 URL만 사용한다.

## Remaining Decisions

- 이미지 OCR 수행 전 추가 마스킹이 필요한지
