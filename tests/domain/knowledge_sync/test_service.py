import pytest
from pydantic import ValidationError
from unittest.mock import patch

from app.common.exceptions import ProviderError
from app.domain.knowledge_sync.schemas import KnowledgeSyncRequest
from app.domain.knowledge_sync.service import KnowledgeSyncService


def test_dept_rr_source_id_must_equal_department_id():
    with pytest.raises(ValidationError):
        KnowledgeSyncRequest(
            source_id=1,
            source_type="DEPT_RR",
            title="R&R",
            content="내용",
            department_id=3,
            department_name="개발1팀",
        )


def test_dept_rr_valid_when_source_id_equals_department_id():
    req = KnowledgeSyncRequest(
        source_id=3,
        source_type="DEPT_RR",
        title="R&R",
        content="내용",
        department_id=3,
        department_name="개발1팀",
    )
    assert req.source_id == req.department_id


def test_routing_case_allows_different_source_id_and_department_id():
    req = KnowledgeSyncRequest(
        source_id=105,
        source_type="ROUTING_CASE",
        title="ERP 처리 사례",
        content="계정 잠금 해제",
        department_id=3,
        department_name="개발1팀",
    )
    assert req.source_id == 105
    assert req.department_id == 3


def test_blank_title_raises_validation_error():
    with pytest.raises(ValidationError):
        KnowledgeSyncRequest(
            source_id=3,
            source_type="DEPT_RR",
            title="   ",
            content="내용",
            department_id=3,
            department_name="개발1팀",
        )


def test_source_id_must_be_positive():
    with pytest.raises(ValidationError):
        KnowledgeSyncRequest(
            source_id=0,
            source_type="DEPT_RR",
            title="R&R",
            content="내용",
            department_id=3,
            department_name="개발1팀",
        )


@pytest.fixture
def service():
    return KnowledgeSyncService()


def _dept_rr_request() -> KnowledgeSyncRequest:
    return KnowledgeSyncRequest(
        source_id=3,
        source_type="DEPT_RR",
        title="개발1팀 R&R",
        content="RAG 파이프라인을 담당한다.",
        department_id=3,
        department_name="개발1팀",
    )


def _routing_case_request() -> KnowledgeSyncRequest:
    return KnowledgeSyncRequest(
        source_id=105,
        source_type="ROUTING_CASE",
        title="ERP 접근 장애 처리 사례",
        content="ERP 계정 잠금 문제를 해결했다.",
        department_id=3,
        department_name="개발1팀",
    )


def test_sync_dept_rr_uses_correct_collection(service):
    with (
        patch("app.domain.knowledge_sync.service.get_embeddings") as mock_emb,
        patch("app.domain.knowledge_sync.service.qdrant_store") as mock_qdrant,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768

        result = service.sync(_dept_rr_request())

    call_kwargs = mock_qdrant.upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "routing_dept_rr"
    assert call_kwargs["metadatas"][0]["type"] == "rr"
    assert result.synced_chunks == 1


def test_sync_routing_case_uses_correct_collection(service):
    with (
        patch("app.domain.knowledge_sync.service.get_embeddings") as mock_emb,
        patch("app.domain.knowledge_sync.service.qdrant_store") as mock_qdrant,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768

        result = service.sync(_routing_case_request())

    call_kwargs = mock_qdrant.upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "routing_cases"
    assert call_kwargs["metadatas"][0]["type"] == "case"
    assert result.synced_chunks == 1


def test_sync_deterministic_point_id(service):
    with (
        patch("app.domain.knowledge_sync.service.get_embeddings") as mock_emb,
        patch("app.domain.knowledge_sync.service.qdrant_store") as mock_qdrant,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        service.sync(_dept_rr_request())
        first_ids = mock_qdrant.upsert.call_args.kwargs["ids"]
        mock_qdrant.reset_mock()
        service.sync(_dept_rr_request())
        second_ids = mock_qdrant.upsert.call_args.kwargs["ids"]

    assert first_ids == second_ids == ["DEPT_RR:3:0"]


def test_sync_embeds_title_and_content_combined(service):
    with (
        patch("app.domain.knowledge_sync.service.get_embeddings") as mock_emb,
        patch("app.domain.knowledge_sync.service.qdrant_store"),
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        service.sync(_dept_rr_request())

    mock_emb.return_value.embed_query.assert_called_once_with("개발1팀 R&R\nRAG 파이프라인을 담당한다.")


def test_sync_embedding_failure_does_not_call_upsert(service):
    with (
        patch("app.domain.knowledge_sync.service.get_embeddings") as mock_emb,
        patch("app.domain.knowledge_sync.service.qdrant_store") as mock_qdrant,
    ):
        mock_emb.return_value.embed_query.side_effect = ProviderError("embedding", "모델 오류")

        with pytest.raises(ProviderError):
            service.sync(_dept_rr_request())

    mock_qdrant.upsert.assert_not_called()


def test_sync_qdrant_failure_raises_provider_error(service):
    with (
        patch("app.domain.knowledge_sync.service.get_embeddings") as mock_emb,
        patch("app.domain.knowledge_sync.service.qdrant_store") as mock_qdrant,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_qdrant.upsert.side_effect = Exception("연결 실패")

        with pytest.raises(ProviderError) as exc_info:
            service.sync(_dept_rr_request())

    assert exc_info.value.provider == "qdrant"


def test_delete_returns_zero_when_not_found(service):
    with patch("app.domain.knowledge_sync.service.qdrant_store") as mock_qdrant:
        mock_qdrant.delete_by_doc_id.return_value = 0

        result = service.delete(source_id=999, source_type="DEPT_RR")

    assert result.deleted_chunks == 0
    assert result.source_id == 999


def test_delete_returns_deleted_count(service):
    with patch("app.domain.knowledge_sync.service.qdrant_store") as mock_qdrant:
        mock_qdrant.delete_by_doc_id.return_value = 1

        result = service.delete(source_id=3, source_type="DEPT_RR")

    assert result.deleted_chunks == 1
    mock_qdrant.delete_by_doc_id.assert_called_once_with("DEPT_RR:3", collection_name="routing_dept_rr")
