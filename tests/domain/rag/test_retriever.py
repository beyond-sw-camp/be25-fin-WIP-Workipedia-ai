from unittest.mock import MagicMock, patch

import pytest

from app.common.exceptions import ProviderError
from app.domain.rag.schemas import RagCandidate


@pytest.fixture
def retriever():
    from app.domain.rag.retriever import RagRetriever
    return RagRetriever()


def _mock_query_result(ids, documents, scores, metadatas=None):
    from app.infra.vector_store.qdrant_store import QueryResult
    return QueryResult(
        ids=ids,
        documents=documents,
        metadatas=metadatas or [{} for _ in ids],
        distances=scores,
    )


def test_search_returns_rag_candidates(retriever):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 768
    mock_result = _mock_query_result(
        ids=["MANUAL:1:0", "MANUAL:1:1"],
        documents=["문서 A", "문서 B"],
        scores=[0.95, 0.80],
        metadatas=[{"source_type": "MANUAL"}, {"source_type": "MANUAL"}],
    )

    with (
        patch("app.domain.rag.retriever.get_embeddings", return_value=mock_embeddings),
        patch("app.domain.rag.retriever.qdrant_store") as mock_store,
    ):
        mock_store.query.return_value = mock_result
        result = retriever.search("FastAPI 사용법", "manual_chunks", top_k=10)

    assert len(result) == 2
    assert all(isinstance(r, RagCandidate) for r in result)
    assert result[0].candidate_id == "MANUAL:1:0"
    assert result[0].score == pytest.approx(0.95)
    assert result[0].text == "문서 A"
    assert result[0].metadata == {"source_type": "MANUAL"}


def test_search_returns_empty_on_no_results(retriever):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 768
    mock_result = _mock_query_result(ids=[], documents=[], scores=[])

    with (
        patch("app.domain.rag.retriever.get_embeddings", return_value=mock_embeddings),
        patch("app.domain.rag.retriever.qdrant_store") as mock_store,
    ):
        mock_store.query.return_value = mock_result
        result = retriever.search("존재하지 않는 내용", "manual_chunks")

    assert result == []


def test_search_top_k_zero_returns_empty(retriever):
    result = retriever.search("질문", "manual_chunks", top_k=0)
    assert result == []


def test_search_raises_provider_error_on_embed_failure(retriever):
    with patch("app.domain.rag.retriever.get_embeddings") as mock_get:
        mock_get.side_effect = ProviderError("embedding", "연결 실패")
        with pytest.raises(ProviderError) as exc_info:
            retriever.search("질문", "manual_chunks")

    assert exc_info.value.provider == "embedding"


def test_search_wraps_embed_exception_as_provider_error(retriever):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.side_effect = ConnectionError("timeout")

    with patch("app.domain.rag.retriever.get_embeddings", return_value=mock_embeddings):
        with pytest.raises(ProviderError) as exc_info:
            retriever.search("질문", "manual_chunks")

    assert exc_info.value.provider == "embedding"


def test_search_wraps_qdrant_exception_as_provider_error(retriever):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 768

    with (
        patch("app.domain.rag.retriever.get_embeddings", return_value=mock_embeddings),
        patch("app.domain.rag.retriever.qdrant_store") as mock_store,
    ):
        mock_store.query.side_effect = Exception("collection not found")
        with pytest.raises(ProviderError) as exc_info:
            retriever.search("질문", "manual_chunks")

    assert exc_info.value.provider == "qdrant"
