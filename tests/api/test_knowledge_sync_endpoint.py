from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.common.exceptions import ProviderError
from app.domain.knowledge_sync.schemas import KnowledgeDeleteResponse, KnowledgeSyncResponse
from app.main import app

client = TestClient(app)

_VALID_DEPT_RR = {
    "sourceId": 3,
    "sourceType": "DEPT_RR",
    "title": "개발1팀 R&R",
    "content": "RAG 파이프라인을 담당한다.",
    "departmentId": 3,
    "departmentName": "개발1팀",
}


def test_sync_returns_200_with_camel_case():
    resp = KnowledgeSyncResponse(source_id=3, synced_chunks=1)
    with patch("app.api.v1.endpoints.knowledge_sync.knowledge_sync_service.sync", return_value=resp):
        r = client.post("/api/v1/knowledge/sync", json=_VALID_DEPT_RR)

    assert r.status_code == 200
    body = r.json()
    assert body["sourceId"] == 3
    assert body["syncedChunks"] == 1


def test_sync_returns_422_on_dept_rr_id_mismatch():
    payload = {**_VALID_DEPT_RR, "sourceId": 1}
    r = client.post("/api/v1/knowledge/sync", json=payload)
    assert r.status_code == 422


def test_sync_returns_422_on_blank_title():
    payload = {**_VALID_DEPT_RR, "title": "   "}
    r = client.post("/api/v1/knowledge/sync", json=payload)
    assert r.status_code == 422


def test_sync_returns_422_on_missing_content():
    payload = {k: v for k, v in _VALID_DEPT_RR.items() if k != "content"}
    r = client.post("/api/v1/knowledge/sync", json=payload)
    assert r.status_code == 422


def test_sync_returns_500_on_provider_error_without_detail_leak():
    with patch(
        "app.api.v1.endpoints.knowledge_sync.knowledge_sync_service.sync",
        side_effect=ProviderError("qdrant", "연결 실패"),
    ):
        r = client.post("/api/v1/knowledge/sync", json=_VALID_DEPT_RR)

    assert r.status_code == 500
    assert "연결 실패" not in r.json().get("detail", "")


def test_delete_returns_200_with_zero_when_not_found():
    resp = KnowledgeDeleteResponse(source_id=999, deleted_chunks=0)
    with patch("app.api.v1.endpoints.knowledge_sync.knowledge_sync_service.delete", return_value=resp):
        r = client.delete("/api/v1/knowledge/999?sourceType=DEPT_RR")

    assert r.status_code == 200
    assert r.json()["deletedChunks"] == 0


def test_delete_returns_422_on_invalid_source_type():
    r = client.delete("/api/v1/knowledge/3?sourceType=MANUAL")
    assert r.status_code == 422


def test_delete_returns_422_on_zero_source_id():
    r = client.delete("/api/v1/knowledge/0?sourceType=DEPT_RR")
    assert r.status_code == 422


def test_delete_returns_500_on_qdrant_failure():
    with patch(
        "app.api.v1.endpoints.knowledge_sync.knowledge_sync_service.delete",
        side_effect=ProviderError("qdrant", "연결 실패"),
    ):
        r = client.delete("/api/v1/knowledge/3?sourceType=DEPT_RR")

    assert r.status_code == 500
    assert "연결 실패" not in r.json().get("detail", "")
