from unittest.mock import MagicMock, patch

import pytest

from app.domain.document.schemas import (
    DocumentIndexRequest,
    DocumentPage,
    PageDocumentItem,
    PageIndexRequest,
)
from app.domain.document.service import DocumentService


@pytest.fixture
def service():
    return DocumentService()


def test_index_returns_chunk_count(service):
    request = DocumentIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="테스트 문서",
        text="이것은 테스트 텍스트입니다. " * 20,
    )
    with (
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_embed.return_value = [[0.1] * 768, [0.2] * 768]
        mock_store.delete_by_doc_id.return_value = 0

        result = service.index(request)

    assert result.source_id == 1
    assert result.indexed_chunks >= 1
    mock_store.delete_by_doc_id.assert_called_once()
    mock_store.upsert.assert_called_once()


def test_index_pdf_pages_stores_page_range_metadata(service):
    request = DocumentIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="PDF 문서",
        text="1페이지 내용 " * 80 + "2페이지 내용 " * 80,
        pages=[
            DocumentPage(page=1, text="1페이지 내용 " * 80),
            DocumentPage(page=2, text="2페이지 내용 " * 80),
        ],
    )
    with (
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_embed.side_effect = lambda chunks: [[0.1] * 768] * len(chunks)
        mock_store.delete_by_doc_id.return_value = 0

        service.index(request)

    metadatas = mock_store.upsert.call_args.kwargs["metadatas"]
    assert all("page_start" in meta for meta in metadatas)
    assert all("page_end" in meta for meta in metadatas)
    assert metadatas[0]["page_start"] == 1
    assert metadatas[-1]["page_end"] == 2


def test_index_pdf_pages_split_long_page_by_chunk_size(service):
    request = DocumentIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="PDF 문서",
        text="긴 페이지 내용 " * 200,
        pages=[
            DocumentPage(page=1, text="긴 페이지 내용 " * 200),
        ],
    )
    with (
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_embed.side_effect = lambda chunks: [[0.1] * 768] * len(chunks)
        mock_store.delete_by_doc_id.return_value = 0

        service.index(request)

    documents = mock_store.upsert.call_args.kwargs["documents"]
    metadatas = mock_store.upsert.call_args.kwargs["metadatas"]
    assert len(documents) > 1
    assert all(len(document) <= 500 for document in documents)
    assert all(meta["page_start"] == 1 for meta in metadatas)
    assert all(meta["page_end"] == 1 for meta in metadatas)


def _index_pages_metadatas(service, request):
    with (
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_embed.side_effect = lambda chunks: [[0.1] * 768] * len(chunks)
        mock_store.delete_by_doc_id.return_value = 0
        result = service.index_pages(request)
    return result, mock_store


def test_index_pages_carries_file_and_page_metadata(service):
    request = PageIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="PDF 문서",
        pages=[
            PageDocumentItem(file_name="file1.pdf", file_key="manuals/1/file1.pdf",
                             file_sort_order=0, page_number=1, global_page_number=1,
                             text="첫번째 페이지 내용 알파"),
        ],
    )
    result, mock_store = _index_pages_metadatas(service, request)

    assert result.source_id == 1
    mock_store.delete_by_doc_id.assert_called_once()
    mock_store.upsert.assert_called_once()
    metadatas = mock_store.upsert.call_args.kwargs["metadatas"]
    required = {"file_name", "file_key", "file_sort_order",
                "page_start", "page_end", "global_page_start", "global_page_end"}
    assert all(required <= meta.keys() for meta in metadatas)
    assert metadatas[0]["file_name"] == "file1.pdf"
    assert metadatas[0]["file_key"] == "manuals/1/file1.pdf"


def test_index_pages_merges_small_pages_into_page_range(service):
    """한 파일 안의 짧은 페이지들은 하나의 청크로 합쳐지고 page_start..page_end 범위로 저장된다."""
    request = PageIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="PDF 문서",
        pages=[
            PageDocumentItem(file_name="file1.pdf", file_key="k1",
                             file_sort_order=0, page_number=1, global_page_number=1,
                             text="첫번째 페이지 알파"),
            PageDocumentItem(file_name="file1.pdf", file_key="k1",
                             file_sort_order=0, page_number=2, global_page_number=2,
                             text="두번째 페이지 베타"),
        ],
    )
    _, mock_store = _index_pages_metadatas(service, request)

    metadatas = mock_store.upsert.call_args.kwargs["metadatas"]
    assert len(metadatas) == 1
    assert metadatas[0]["page_start"] == 1
    assert metadatas[0]["page_end"] == 2
    assert metadatas[0]["global_page_start"] == 1
    assert metadatas[0]["global_page_end"] == 2


def test_index_pages_does_not_cross_file_boundary(service):
    """다른 파일의 짧은 페이지는 합치지 않는다 — 파일별로 청크가 분리된다."""
    request = PageIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="PDF 문서",
        pages=[
            PageDocumentItem(file_name="file1.pdf", file_key="k1",
                             file_sort_order=0, page_number=1, global_page_number=1,
                             text="파일하나 알파"),
            PageDocumentItem(file_name="file2.pdf", file_key="k2",
                             file_sort_order=1, page_number=1, global_page_number=2,
                             text="파일둘 베타"),
        ],
    )
    _, mock_store = _index_pages_metadatas(service, request)

    metadatas = mock_store.upsert.call_args.kwargs["metadatas"]
    assert len(metadatas) == 2
    assert metadatas[0]["file_name"] == "file1.pdf"
    assert metadatas[0]["page_start"] == 1 and metadatas[0]["page_end"] == 1
    assert metadatas[1]["file_name"] == "file2.pdf"
    assert metadatas[1]["global_page_start"] == 2


def test_index_pages_splits_long_page_within_same_page(service):
    """한 페이지가 chunk_size보다 길면 여러 청크로 쪼개지되 모두 같은 페이지 번호를 가진다."""
    request = PageIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="PDF 문서",
        pages=[
            PageDocumentItem(file_name="file1.pdf", file_key="k1",
                             file_sort_order=0, page_number=3, global_page_number=3,
                             text="긴 페이지 내용 " * 200),
        ],
    )
    _, mock_store = _index_pages_metadatas(service, request)

    metadatas = mock_store.upsert.call_args.kwargs["metadatas"]
    assert len(metadatas) >= 2
    assert all(meta["page_start"] == 3 and meta["page_end"] == 3 for meta in metadatas)
    assert all(meta["global_page_start"] == 3 for meta in metadatas)


def test_index_pages_raises_on_invalid_source_type(service):
    request = PageIndexRequest(
        source_id=1,
        source_type="UNKNOWN",
        title="문서",
        pages=[PageDocumentItem(file_name="f.pdf", file_key="k", file_sort_order=0,
                                page_number=1, global_page_number=1, text="내용")],
    )
    with pytest.raises(ValueError):
        service.index_pages(request)


def test_index_embed_first_then_delete(service):
    """임베딩 성공 후 기존 청크를 삭제한다 (순서 보장)."""
    request = DocumentIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="테스트",
        text="이것은 테스트 텍스트입니다. " * 20,
    )
    call_order = []
    with (
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_embed.side_effect = lambda chunks: call_order.append("embed") or [[0.1] * 768] * len(chunks)
        mock_store.delete_by_doc_id.side_effect = lambda *a, **kw: call_order.append("delete")
        mock_store.upsert.side_effect = lambda **kw: call_order.append("upsert")

        service.index(request)

    assert call_order == ["embed", "delete", "upsert"], f"순서 오류: {call_order}"


def test_index_preserves_existing_chunks_on_embed_failure(service):
    """임베딩 실패 시 기존 청크를 삭제하지 않는다."""
    from app.common.exceptions import ProviderError

    request = DocumentIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="테스트",
        text="이것은 테스트 텍스트입니다. " * 20,
    )
    with (
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_embed.side_effect = ProviderError("embedding", "timeout")

        with pytest.raises(Exception):
            service.index(request)

        mock_store.delete_by_doc_id.assert_not_called()


def test_index_raises_on_invalid_source_type(service):
    request = DocumentIndexRequest(
        source_id=1,
        source_type="INVALID_TYPE",
        title="테스트",
        text="텍스트",
    )
    with pytest.raises(ValueError, match="지원하지 않는 source_type"):
        service.index(request)


def test_index_raises_on_blank_text(service):
    request = DocumentIndexRequest(
        source_id=1,
        source_type="MANUAL",
        title="테스트",
        text="   ",
    )
    with pytest.raises(ValueError, match="텍스트가 비어"):
        service.index(request)


def test_worki_uses_full_masking(service):
    """WORKI는 전화번호·이메일 패턴까지 마스킹한다."""
    from app.common.masking import masker_for, _OPTIONAL_PATTERNS
    worki_masker = masker_for("WORKI")
    result = worki_masker.mask("연락처 010-1234-5678")
    assert "[전화번호]" in result


def test_manual_skips_optional_masking(service):
    """MANUAL은 전화번호·이메일을 마스킹하지 않는다."""
    from app.common.masking import masker_for
    manual_masker = masker_for("MANUAL")
    result = manual_masker.mask("연락처 010-1234-5678")
    assert "010-1234-5678" in result


def test_delete_returns_chunk_count(service):
    with patch("app.domain.document.service.qdrant_store") as mock_store:
        mock_store.delete_by_doc_id.return_value = 5

        result = service.delete(1, "MANUAL")

    assert result.source_id == 1
    assert result.deleted_chunks == 5
    mock_store.delete_by_doc_id.assert_called_once_with("MANUAL:1", collection_name="manual_chunks")


def test_delete_raises_on_invalid_source_type(service):
    with pytest.raises(ValueError, match="지원하지 않는 source_type"):
        service.delete(1, "INVALID_TYPE")


def test_worki_uses_smaller_chunks_than_manual(service):
    """WORKI는 MANUAL보다 작은 chunk_size로 청킹된다."""
    from app.core.config import CHUNK_CONFIG
    assert CHUNK_CONFIG["WORKI"]["chunk_size"] < CHUNK_CONFIG["MANUAL"]["chunk_size"]
    assert CHUNK_CONFIG["WORKI"]["chunk_overlap"] < CHUNK_CONFIG["MANUAL"]["chunk_overlap"]


def test_chunk_config_applied_per_source_type(service):
    """source_type에 맞는 청킹 파라미터가 chunk_text에 전달된다."""
    request = DocumentIndexRequest(
        source_id=1,
        source_type="WORKI",
        title="워키 게시글",
        text="짧은 게시글 내용입니다. " * 10,
    )
    with (
        patch("app.domain.document.service.chunk_text") as mock_chunk,
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_chunk.return_value = ["chunk1"]
        mock_embed.return_value = [[0.1] * 768]
        mock_store.delete_by_doc_id.return_value = 0

        service.index(request)

    call_kwargs = mock_chunk.call_args
    assert call_kwargs.kwargs.get("chunk_size") == 300
    assert call_kwargs.kwargs.get("chunk_overlap") == 50


def test_different_source_types_use_different_collections(service):
    """같은 source_id라도 source_type이 다르면 다른 collection을 사용한다."""
    with patch("app.domain.document.service.qdrant_store") as mock_store:
        mock_store.delete_by_doc_id.return_value = 3

        service.delete(1, "MANUAL")
        service.delete(1, "WORKI")

    calls = mock_store.delete_by_doc_id.call_args_list
    assert calls[0].kwargs["collection_name"] == "manual_chunks"
    assert calls[1].kwargs["collection_name"] == "worki_chunks"
