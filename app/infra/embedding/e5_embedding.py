from functools import lru_cache

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from app.core.config import EMBEDDING_MODEL_MAP
from .base import BaseEmbeddingClient


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_MAP["e5"], device="cpu")


class E5Embeddings(Embeddings):
    """multilingual-e5 embedding with asymmetric query/passage prefixes."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        inputs = [f"passage: {text}" for text in texts]
        vectors = _load_model().encode(inputs, normalize_embeddings=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = _load_model().encode([f"query: {text}"], normalize_embeddings=True)
        return vector[0].tolist()


class E5EmbeddingClient(BaseEmbeddingClient):
    def get_embeddings(self) -> Embeddings:
        return E5Embeddings()
