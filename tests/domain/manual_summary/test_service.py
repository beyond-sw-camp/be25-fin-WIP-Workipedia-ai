from unittest.mock import MagicMock, patch

import pytest

from app.common.exceptions import ProviderError
from app.domain.manual_summary.schemas import ManualChangeSummaryRequest
from app.domain.manual_summary.service import manual_summary_service


def _request() -> ManualChangeSummaryRequest:
    return ManualChangeSummaryRequest(
        title="위키피디아 소개서",
        content_diff="@@ line 12 @@\n- 이전 문구\n+ 새 문구",
        update_reason="PDF_UPLOAD",
    )


def test_summarize_returns_stripped_one_line():
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="  위키피디아 소개서 문구가 새 버전으로 수정되었습니다.  ")
    with patch("app.domain.manual_summary.service.get_llm", return_value=fake_llm):
        result = manual_summary_service.summarize(_request())
    assert result.summary == "위키피디아 소개서 문구가 새 버전으로 수정되었습니다."


def test_summarize_blank_llm_output_raises():
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="   ")
    with patch("app.domain.manual_summary.service.get_llm", return_value=fake_llm):
        with pytest.raises(ProviderError):
            manual_summary_service.summarize(_request())


def test_request_parses_camelcase_aliases():
    req = ManualChangeSummaryRequest.model_validate(
        {"title": "t", "contentDiff": "d", "updateReason": "PDF_UPLOAD"}
    )
    assert req.content_diff == "d"
    assert req.update_reason == "PDF_UPLOAD"
