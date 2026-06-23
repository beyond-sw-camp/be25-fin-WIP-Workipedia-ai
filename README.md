# be25-fin-1team-project1
be25-fin-1team-project1

## E5 임베딩 로컬 테스트

`intfloat/multilingual-e5-base`를 테스트하려면 아래 환경변수를 사용한다.

```env
EMBEDDING_PROVIDER=e5
```

E5 provider는 문서 임베딩에는 `passage: `, 질문 임베딩에는 `query: ` prefix를 붙이고 정규화된 768차원 벡터를 생성한다.
기존 OpenAI 또는 Ollama 임베딩으로 만든 Qdrant 컬렉션과 차원이 다르므로, 테스트 전 `manual_chunks` 컬렉션을 삭제하고 다시 인덱싱해야 한다.
