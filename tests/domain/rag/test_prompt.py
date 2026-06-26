from app.domain.rag.prompt import build_context, build_system_prompt
from app.domain.rag.schemas import RerankedCandidate


def _make_candidate(cid: str, text: str) -> RerankedCandidate:
    return RerankedCandidate(candidate_id=cid, text=text, score=1.0, rank=1)


def test_build_context_contains_id_and_text():
    candidates = [_make_candidate("MANUAL:1:0", "휴가 신청은 HR 포털에서")]
    ctx = build_context(candidates)
    assert "[ID: MANUAL:1:0]" in ctx
    assert "휴가 신청은 HR 포털에서" in ctx


def test_build_context_multiple_candidates():
    candidates = [
        _make_candidate("MANUAL:1:0", "A"),
        _make_candidate("MANUAL:1:1", "B"),
    ]
    ctx = build_context(candidates)
    assert "[ID: MANUAL:1:0]" in ctx
    assert "[ID: MANUAL:1:1]" in ctx


def test_build_system_prompt_without_custom():
    prompt = build_system_prompt(custom_prompt=None)
    assert "Workipedia" in prompt
    assert "cited_ids" in prompt
    assert "INSUFFICIENT_CONTEXT" in prompt


def test_build_system_prompt_with_custom():
    prompt = build_system_prompt(custom_prompt="항상 존댓말로 답하세요.")
    assert "항상 존댓말로 답하세요." in prompt
