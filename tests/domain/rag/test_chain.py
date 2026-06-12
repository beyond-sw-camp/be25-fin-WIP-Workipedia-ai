import json
from unittest.mock import MagicMock, patch

import pytest

from app.common.exceptions import ProviderError
from app.domain.rag.schemas import GeneratedAnswer, RagResult, RagStatus, RerankedCandidate


def _make_candidate(cid: str, text: str = "내용", score: float = 1.0, rank: int = 1) -> RerankedCandidate:
    return RerankedCandidate(candidate_id=cid, text=text, score=score, rank=rank)


def _mock_llm_response(status: str, answer: str | None = None, cited_ids: list[str] | None = None):
    payload = {"status": status, "answer": answer, "cited_ids": cited_ids or []}
    mock_response = MagicMock()
    mock_response.content = json.dumps(payload, ensure_ascii=False)
    return mock_response


@pytest.fixture
def chain():
    from app.domain.rag.chain import RagChain
    return RagChain()


# ── NO_RESULT 조건 ──────────────────────────────────────────────────────────

def test_no_result_when_candidates_empty(chain):
    result = chain.generate("질문", candidates=[])
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_score_below_threshold(chain):
    result = chain.generate("질문", candidates=[_make_candidate("MANUAL:1:0", score=-1.0)])
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_status_insufficient_context(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _mock_llm_response("INSUFFICIENT_CONTEXT")
        result = chain.generate("질문", candidates=candidates)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_cited_ids_empty(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _mock_llm_response("ANSWER", "답변", [])
        result = chain.generate("질문", candidates=candidates)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_cited_id_not_in_candidates(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _mock_llm_response("ANSWER", "답변", ["MANUAL:9:9"])
        result = chain.generate("질문", candidates=candidates)
    assert result.status == RagStatus.NO_RESULT


# ── SUCCESS ──────────────────────────────────────────────────────────────────

def test_success_with_valid_answer(chain):
    candidates = [_make_candidate("MANUAL:1:0", text="휴가 신청은 HR 포털", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _mock_llm_response(
            "ANSWER", "휴가는 HR 포털에서 신청합니다.", ["MANUAL:1:0"]
        )
        result = chain.generate("휴가 신청 방법", candidates=candidates)

    assert result.status == RagStatus.SUCCESS
    assert isinstance(result.answer, GeneratedAnswer)
    assert result.answer.answer == "휴가는 HR 포털에서 신청합니다."
    assert len(result.answer.references) == 1
    assert result.answer.references[0].candidate_id == "MANUAL:1:0"


def test_custom_prompt_included_in_system_message(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        invoke_mock = mock_llm.return_value.invoke
        invoke_mock.return_value = _mock_llm_response("ANSWER", "답변", ["MANUAL:1:0"])
        chain.generate("질문", candidates=candidates, custom_prompt="항상 존댓말")

    messages = invoke_mock.call_args[0][0]
    assert "항상 존댓말" in messages[0].content


def test_duplicate_cited_ids_are_deduplicated(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _mock_llm_response(
            "ANSWER", "답변", ["MANUAL:1:0", "MANUAL:1:0"]
        )
        result = chain.generate("질문", candidates=candidates)

    assert result.status == RagStatus.SUCCESS
    assert len(result.answer.references) == 1


def test_success_when_response_has_json_fence(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    fenced = '```json\n{"status":"ANSWER","answer":"답변","cited_ids":["MANUAL:1:0"]}\n```'
    mock_response = MagicMock()
    mock_response.content = fenced

    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        result = chain.generate("질문", candidates=candidates)

    assert result.status == RagStatus.SUCCESS


# ── ERROR ─────────────────────────────────────────────────────────────────

def test_error_on_provider_error_no_retry(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = ProviderError("llm", "timeout")
        result = chain.generate("질문", candidates=candidates)

    assert result.status == RagStatus.ERROR
    assert mock_llm.return_value.invoke.call_count == 1


def test_error_after_two_json_parse_failures(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    bad_response = MagicMock()
    bad_response.content = "이건 JSON이 아님"

    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = bad_response
        result = chain.generate("질문", candidates=candidates)

    assert result.status == RagStatus.ERROR
    assert mock_llm.return_value.invoke.call_count == 2


def test_success_on_second_attempt_after_parse_failure(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    bad_response = MagicMock()
    bad_response.content = "이건 JSON이 아님"
    good_response = _mock_llm_response("ANSWER", "답변", ["MANUAL:1:0"])

    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = [bad_response, good_response]
        result = chain.generate("질문", candidates=candidates)

    assert result.status == RagStatus.SUCCESS
    assert mock_llm.return_value.invoke.call_count == 2


def test_error_when_answer_status_has_null_answer(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _mock_llm_response("ANSWER", None, ["MANUAL:1:0"])
        result = chain.generate("질문", candidates=candidates)

    assert result.status == RagStatus.ERROR
    assert mock_llm.return_value.invoke.call_count == 2


def test_error_when_answer_is_whitespace_only(chain):
    candidates = [_make_candidate("MANUAL:1:0", score=2.0)]
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _mock_llm_response("ANSWER", "   ", ["MANUAL:1:0"])
        result = chain.generate("질문", candidates=candidates)

    assert result.status == RagStatus.ERROR
