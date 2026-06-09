# ADR 009 - Elasticsearch Strategy

> 문서 유형: ADR
> 상태: Accepted
> 정본 위치: `docs/adr/search-strategy.md`
> 관련 문서: `docs/adr/rag-strategy.md`, `docs/reference/trd.md`, `docs/domain-guides/chatbot-rag.md`
> 버전: v0.2
> 최종 수정: 2026-06-09

## Context

BE에서 워키/매뉴얼 등 문서에 대한 전문 검색과 kNN 유사도 검색을 수행할 검색 엔진이 필요하다.

V1 스키마는 `embedding_json` 컬럼을 RDB에 두는 최소 구현으로 시작했다.

팀 논의 결과, 검색 품질과 확장성을 고려해 Elasticsearch를 BE의 검색 엔진으로 채택하기로 했다.

**AI 서버(Python FastAPI)는 별도로 ChromaDB를 RAG Vector Store로 사용한다. 이 ADR의 Elasticsearch 결정은 BE(Spring Boot) 범위에 한정된다.**

담당: 민정기

## Decision

BE의 검색 엔진으로 **Elasticsearch**를 사용한다.

- docker-compose에 Elasticsearch 컨테이너를 추가한다.
- 매뉴얼/워키 chunk를 Elasticsearch에 인덱싱한다.
- 유사도 검색은 Elasticsearch의 kNN(k-nearest neighbor) 검색을 사용한다.
- Spring 애플리케이션에서는 adapter 패턴으로 격리한다 (`rag/adapter/VectorSearchClient`).
- RDB의 `embedding_json` 컬럼은 fallback 또는 메타데이터 저장 목적으로 유지한다.
- AI 서버의 RAG Vector Store(ChromaDB)와는 별개 시스템이다.

## Consequences

- BE 검색 품질이 RDB 기반보다 향상된다.
- docker-compose에 Elasticsearch 서비스가 추가되어 로컬 환경 요구사항이 늘어난다.
- 민정기가 Elasticsearch 인덱스 설계와 BE adapter 구현을 담당한다.
- AI 서버(김진혁)는 ChromaDB를 직접 사용하며 Elasticsearch에 의존하지 않는다.
- Elasticsearch 장애 시 RDB 기반 fallback 경로를 고려할 수 있다.

## Confirmed Boundary

- BE 검색 엔진은 현재 Docker 환경의 Elasticsearch 8.15.3을 기준으로 한다.
- AI RAG Vector Store는 ChromaDB를 사용한다.
- Elasticsearch 인덱스 설정과 한국어 analyzer는 BE 검색 구현 범위에서 관리한다.
- RDB `embedding_json` 컬럼의 제거 여부는 BE migration에서 별도로 결정한다.
