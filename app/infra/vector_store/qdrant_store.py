import uuid as _uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import EMBEDDING_DIM_MAP, RETRIEVAL_TOP_K, settings


@dataclass
class QueryResult:
    ids: list[str]
    documents: list[str]
    metadatas: list[dict]
    distances: list[float]


class QdrantStore:
    def __init__(self) -> None:
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        return self._client

    def _point_id(self, chunk_id: str) -> str:
        """문자열 청크 ID를 Qdrant 호환 UUID로 변환한다."""
        return str(_uuid.uuid5(_uuid.NAMESPACE_OID, chunk_id))

    def _ensure_collection(self, name: str) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM_MAP[settings.embedding_provider.value],
                    distance=Distance.COSINE,
                ),
            )

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict] | None = None,
        collection_name: str = "workipedia",
    ) -> None:
        self._ensure_collection(collection_name)
        metas = metadatas or [{} for _ in ids]
        points = [
            PointStruct(
                id=self._point_id(chunk_id),
                vector=embedding,
                payload={"_chunk_id": chunk_id, "text": doc, **meta},
            )
            for chunk_id, doc, embedding, meta in zip(ids, documents, embeddings, metas)
        ]
        self.client.upsert(collection_name=collection_name, points=points)

    def query(
        self,
        query_embedding: list[float],
        top_k: int = RETRIEVAL_TOP_K,
        collection_name: str = "workipedia",
    ) -> QueryResult:
        # _ensure_collection을 호출하지 않는다. 존재하지 않는 collection을 빈 결과로 처리하면
        # 오타나 잘못된 collection명이 NO_RESULT로 조용히 통과되어 디버깅이 어렵다.
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            limit=top_k,
            with_payload=True,
        )
        if not results:
            return QueryResult(ids=[], documents=[], metadatas=[], distances=[])
        ids, documents, metadatas, distances = [], [], [], []
        for hit in results:
            payload = hit.payload or {}
            ids.append(payload.get("_chunk_id", str(hit.id)))
            documents.append(payload.get("text", ""))
            meta = {k: v for k, v in payload.items() if k not in ("_chunk_id", "text")}
            metadatas.append(meta)
            distances.append(hit.score)
        return QueryResult(ids=ids, documents=documents, metadatas=metadatas, distances=distances)

    def delete(
        self,
        ids: list[str],
        collection_name: str = "workipedia",
    ) -> None:
        point_ids = [self._point_id(chunk_id) for chunk_id in ids]
        self.client.delete(collection_name=collection_name, points_selector=point_ids)

    def delete_by_doc_id(
        self,
        doc_id: str,
        collection_name: str = "workipedia",
    ) -> int:
        """doc_id 메타데이터로 청크를 조회 후 전체 삭제. 삭제된 청크 수를 반환한다."""
        self._ensure_collection(collection_name)
        results, _ = self.client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
            limit=10000,
            with_payload=False,
            with_vectors=False,
        )
        if not results:
            return 0
        self.client.delete(
            collection_name=collection_name,
            points_selector=[p.id for p in results],
        )
        return len(results)


qdrant_store = QdrantStore()
