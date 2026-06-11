from dataclasses import dataclass

import chromadb
from chromadb import Collection

from app.core.config import settings


@dataclass
class QueryResult:
    ids: list[str]
    documents: list[str]
    metadatas: list[dict]
    distances: list[float]


class ChromaStore:
    def __init__(self) -> None:
        self._client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )

    def get_collection(
        self,
        name: str = settings.chroma_collection_name,
        embedding_model: str | None = None,
    ) -> Collection:
        metadata = {"embedding_model": embedding_model or settings.embedding_model}
        return self._client.get_or_create_collection(name, metadata=metadata)

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict] | None = None,
        collection_name: str = settings.chroma_collection_name,
    ) -> None:
        collection = self.get_collection(collection_name)
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas or [{} for _ in ids],
        )

    def query(
        self,
        query_embedding: list[float],
        top_k: int = settings.retrieval_top_k,
        collection_name: str = settings.chroma_collection_name,
    ) -> QueryResult:
        collection = self.get_collection(collection_name)
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()) if collection.count() > 0 else 1,
            include=["documents", "metadatas", "distances"],
        )
        if not result["ids"] or not result["ids"][0]:
            return QueryResult(ids=[], documents=[], metadatas=[], distances=[])
        return QueryResult(
            ids=result["ids"][0],
            documents=result["documents"][0],
            metadatas=result["metadatas"][0],
            distances=result["distances"][0],
        )

    def delete(
        self,
        ids: list[str],
        collection_name: str = settings.chroma_collection_name,
    ) -> None:
        collection = self.get_collection(collection_name)
        collection.delete(ids=ids)


chroma_store = ChromaStore()
