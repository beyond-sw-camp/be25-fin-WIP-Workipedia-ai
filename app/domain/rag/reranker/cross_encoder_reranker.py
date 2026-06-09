from sentence_transformers import CrossEncoder

from app.core.config import settings
from .base import BaseReranker


class CrossEncoderReranker(BaseReranker):
    def __init__(self, model_name: str = settings.reranker_model) -> None:
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[int]:
        pairs = [(query, doc) for doc in documents]
        scores = self._model.predict(pairs)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return ranked[:top_k]
