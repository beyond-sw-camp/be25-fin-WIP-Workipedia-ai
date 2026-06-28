import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.common.exceptions import ProviderError
from app.domain.ticket_draft.schemas import TicketDraftRequest
from app.domain.ticket_draft.service import TicketDraftService


@pytest.fixture
def service():
    return TicketDraftService()


def _patch_llm(content):
    # get_llm().invoke(messages).content == content 가 되도록 패치한다.
    mock = patch("app.domain.ticket_draft.service.get_llm")
    started = mock.start()
    started.return_value.invoke.return_value.content = content
    return mock


def test_blank_raw_text_raises_validation_error():
    with pytest.raises(ValidationError):
        TicketDraftRequest(raw_text="   ")


def test_draft_returns_parsed_title_and_content(service):
    llm_out = json.dumps({"title": "연차 잔여일수 문의", "content": "올해 잔여 연차를 확인하고 싶습니다."})
    m = _patch_llm(llm_out)
    try:
        res = service.draft(TicketDraftRequest(raw_text="올해 연차 얼마나 써야돼?"))
    finally:
        m.stop()

    assert res.title == "연차 잔여일수 문의"
    assert "연차" in res.content


def test_draft_strips_code_fence_and_surrounding_text(service):
    llm_out = "```json\n" + json.dumps({"title": "제목", "content": "내용입니다."}) + "\n```"
    m = _patch_llm(llm_out)
    try:
        res = service.draft(TicketDraftRequest(raw_text="비품 신청하고 싶어요"))
    finally:
        m.stop()

    assert res.title == "제목"
    assert res.content == "내용입니다."


def test_draft_falls_back_to_raw_when_not_json(service):
    m = _patch_llm("이건 JSON이 아닙니다.")
    try:
        res = service.draft(TicketDraftRequest(raw_text="비품 신청하고 싶어요"))
    finally:
        m.stop()

    # 파싱 실패 시 원문을 content로, 첫 줄을 title로 fallback.
    assert res.content == "비품 신청하고 싶어요"
    assert res.title


def test_draft_propagates_provider_error_on_llm_failure(service):
    with patch("app.domain.ticket_draft.service.get_llm") as mock_get_llm:
        mock_get_llm.return_value.invoke.side_effect = Exception("LLM 오류")
        with pytest.raises(ProviderError):
            service.draft(TicketDraftRequest(raw_text="네트워크 안돼요"))
