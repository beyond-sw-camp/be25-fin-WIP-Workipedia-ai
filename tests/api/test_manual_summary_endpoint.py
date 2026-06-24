from unittest.mock import patch

from fastapi.testclient import TestClient

from app.common.exceptions import ProviderError
from app.domain.manual_summary.schemas import ManualChangeSummaryResponse
from app.main import app

client = TestClient(app)

_VALID_BODY = {
    "title": "위키피디아 소개서",
    "contentDiff": "@@ line 12 @@\n- 이전 문구\n+ 새 문구",
    "updateReason": "PDF_UPLOAD",
}


def test_change_summary_returns_200_with_summary():
    with patch(
        "app.api.v1.endpoints.manual_summary.manual_summary_service.summarize",
        return_value=ManualChangeSummaryResponse(summary="소개서 문구가 수정되었습니다."),
    ):
        response = client.post("/api/v1/manual/change-summary", json=_VALID_BODY)

    assert response.status_code == 200
    assert response.json()["summary"] == "소개서 문구가 수정되었습니다."


def test_change_summary_returns_422_on_blank_title():
    body = dict(_VALID_BODY, title="   ")
    response = client.post("/api/v1/manual/change-summary", json=body)
    assert response.status_code == 422


def test_change_summary_returns_500_on_provider_error():
    with patch(
        "app.api.v1.endpoints.manual_summary.manual_summary_service.summarize",
        side_effect=ProviderError("llm", "LLM 호출 실패"),
    ):
        response = client.post("/api/v1/manual/change-summary", json=_VALID_BODY)
    assert response.status_code == 500
