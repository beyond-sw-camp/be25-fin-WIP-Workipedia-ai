from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("app.domain.rag.reranker.cross_encoder_reranker.get_reranker"):
        from app.main import app
        return TestClient(app)


def _payload():
    return {
        "source_id": 1,
        "source_type": "MANUAL",
        "title": "PDF 문서",
        "pages": [
            {"file_name": "file1.pdf", "file_key": "manuals/1/file1.pdf",
             "file_sort_order": 0, "page_number": 1, "global_page_number": 1,
             "text": "1페이지 내용 " * 80},
            {"file_name": "file2.pdf", "file_key": "manuals/1/file2.pdf",
             "file_sort_order": 1, "page_number": 1, "global_page_number": 2,
             "text": "다른 파일 내용 " * 80},
        ],
    }


def test_ingest_pages_indexes_and_returns_count(client):
    with (
        patch("app.domain.document.service.embed_texts") as mock_embed,
        patch("app.domain.document.service.qdrant_store") as mock_store,
    ):
        mock_embed.side_effect = lambda chunks: [[0.1] * 768] * len(chunks)
        mock_store.delete_by_doc_id.return_value = 0

        response = client.post("/api/v1/documents/ingest-pages", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["source_id"] == 1
    assert body["indexed_chunks"] >= 2

    metadatas = mock_store.upsert.call_args.kwargs["metadatas"]
    assert metadatas[0]["file_name"] == "file1.pdf"
    assert metadatas[-1]["global_page_start"] == 2


def test_ingest_pages_rejects_empty_pages(client):
    payload = _payload()
    payload["pages"] = []
    response = client.post("/api/v1/documents/ingest-pages", json=payload)
    assert response.status_code == 422


def test_ingest_pages_rejects_unsupported_source_type(client):
    payload = _payload()
    payload["source_type"] = "UNKNOWN"
    with (
        patch("app.domain.document.service.embed_texts"),
        patch("app.domain.document.service.qdrant_store"),
    ):
        response = client.post("/api/v1/documents/ingest-pages", json=payload)
    assert response.status_code == 422
