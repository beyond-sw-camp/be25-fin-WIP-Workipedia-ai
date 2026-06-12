from unittest.mock import MagicMock, patch

import pytest

from app.domain.rag.schemas import RagCandidate, RerankedCandidate


@pytest.fixture
def candidates():
    return [
        RagCandidate(candidate_id="MANUAL:1:0", text="FastAPI 설치 방법", score=0.9),
        RagCandidate(candidate_id="MANUAL:1:1", text="Python 가상환경 설정", score=0.8),
        RagCandidate(candidate_id="MANUAL:1:2", text="Docker 컨테이너 실행", score=0.7),
    ]


@pytest.fixture
def reranker():
    mock_model = MagicMock()
    with patch("app.domain.rag.reranker.cross_encoder_reranker.CrossEncoder", return_value=mock_model):
        from app.domain.rag.reranker.cross_encoder_reranker import CrossEncoderReranker
        r = CrossEncoderReranker()
    r._model = mock_model
    return r


def test_rerank_returns_reranked_candidates(reranker, candidates):
    reranker._model.predict.return_value = [0.3, 0.9, 0.6]

    result = reranker.rerank("FastAPI 설치", candidates, top_k=2)

    assert len(result) == 2
    assert all(isinstance(r, RerankedCandidate) for r in result)


def test_rerank_rank_matches_score_order(reranker, candidates):
    reranker._model.predict.return_value = [0.3, 0.9, 0.6]

    result = reranker.rerank("FastAPI 설치", candidates, top_k=3)

    assert result[0].rank == 1
    assert result[0].score == pytest.approx(0.9)
    assert result[0].candidate_id == "MANUAL:1:1"
    assert result[0].text == "Python 가상환경 설정"
    assert result[0].retrieval_score == pytest.approx(0.8)

    assert result[1].rank == 2
    assert result[1].score == pytest.approx(0.6)
    assert result[1].candidate_id == "MANUAL:1:2"

    assert result[2].rank == 3
    assert result[2].score == pytest.approx(0.3)
    assert result[2].candidate_id == "MANUAL:1:0"


def test_rerank_top_k_limits_results(reranker, candidates):
    reranker._model.predict.return_value = [0.3, 0.9, 0.6]

    result = reranker.rerank("FastAPI 설치", candidates, top_k=1)

    assert len(result) == 1
    assert result[0].rank == 1


def test_rerank_empty_candidates(reranker):
    result = reranker.rerank("FastAPI 설치", [], top_k=5)

    assert result == []
    reranker._model.predict.assert_not_called()


def test_rerank_top_k_zero_returns_empty(reranker, candidates):
    result = reranker.rerank("FastAPI 설치", candidates, top_k=0)

    assert result == []
    reranker._model.predict.assert_not_called()


def test_rerank_negative_top_k_returns_empty(reranker, candidates):
    result = reranker.rerank("FastAPI 설치", candidates, top_k=-1)

    assert result == []
    reranker._model.predict.assert_not_called()


def test_rerank_predict_failure_raises_provider_error(reranker, candidates):
    from app.common.exceptions import ProviderError

    reranker._model.predict.side_effect = RuntimeError("CUDA out of memory")

    with pytest.raises(ProviderError) as exc_info:
        reranker.rerank("FastAPI 설치", candidates, top_k=3)

    assert exc_info.value.provider == "cross-encoder"


def test_reranker_model_load_failure():
    from app.common.exceptions import ProviderError
    from app.domain.rag.reranker.cross_encoder_reranker import CrossEncoderReranker

    with patch("app.domain.rag.reranker.cross_encoder_reranker.CrossEncoder") as mock_ce:
        mock_ce.side_effect = OSError("model not found")
        with pytest.raises(ProviderError) as exc_info:
            CrossEncoderReranker()

    assert exc_info.value.provider == "cross-encoder"


def test_get_reranker_returns_cached_instance():
    from app.domain.rag.reranker.cross_encoder_reranker import get_reranker

    mock_instance = MagicMock()
    with patch("app.domain.rag.reranker.cross_encoder_reranker.CrossEncoderReranker", return_value=mock_instance):
        get_reranker.cache_clear()
        r1 = get_reranker()
        r2 = get_reranker()

    assert r1 is r2
    get_reranker.cache_clear()
