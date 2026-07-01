from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.common.exceptions import ProviderError, provider_call
from app.core.config import settings
from app.domain.rag.schemas import RagCandidate, RerankedCandidate
from .base import BaseReranker


class CrossEncoderReranker(BaseReranker):
    def __init__(self, model_name: str | None = None) -> None:
        model_name = model_name or settings.rag_reranker_model
        try:
            self._model = CrossEncoder(model_name)
        except Exception as e:
            raise ProviderError("cross-encoder", str(e)) from e

    def rerank(
        self,
        query: str,
        candidates: list[RagCandidate],
        top_k: int,
    ) -> list[RerankedCandidate]:
        if not candidates or top_k <= 0:
            return []

        # (질문, 문서) 쌍을 Cross-Encoder에 넣어 관련도 점수 계산. 실패 시 ProviderError("cross-encoder") 발생
        pairs = [(query, c.text) for c in candidates]
        with provider_call("cross-encoder"):
            scores = self._model.predict(pairs)

        # 점수 높은 순으로 정렬 후 상위 top_k개만 반환. rank는 1-based
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [
            RerankedCandidate(
                candidate_id=candidates[i].candidate_id,
                text=candidates[i].text,
                score=float(scores[i]),
                rank=rank + 1,
                metadata=candidates[i].metadata,
                retrieval_score=candidates[i].score,  # 1단계 벡터 유사도 점수 보존
            )
            for rank, i in enumerate(order[:top_k])
        ]


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoderReranker:
    # 첫 호출 시에만 모델 로드, 이후 캐시 반환 → 서버 기동 시 lifespan에서 preload
    return CrossEncoderReranker()
