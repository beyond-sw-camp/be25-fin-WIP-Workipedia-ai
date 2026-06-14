from unittest.mock import MagicMock, patch
import json
from app.domain.chatbot.schemas import SessionMessage
from app.domain.rag.schemas import RagStatus, RerankedCandidate


def _candidate(cid="MANUAL:1:0", score=1.0):
    return RerankedCandidate(candidate_id=cid, text="내용", score=score, rank=1, metadata={"title": "문서"})


def _mock_llm(answer="답변", cited_ids=None):
    if cited_ids is None:
        cited_ids = ["MANUAL:1:0"]
    resp = MagicMock()
    resp.content = json.dumps({"status": "ANSWER", "answer": answer, "cited_ids": cited_ids})
    return resp


def test_generate_with_session_context_inserts_history():
    from app.domain.rag.chain import RagChain
    chain = RagChain()
    context = [
        SessionMessage(message_id=1, sender_type="USER", content="연차 어떻게?"),
        SessionMessage(message_id=2, sender_type="ASSISTANT", content="HR 포털"),
    ]
    captured_messages = []
    def fake_invoke(messages):
        captured_messages.extend(messages)
        return _mock_llm()
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = fake_invoke
        result = chain.generate("며칠 전에?", [_candidate()], session_context=context)
    assert result.status == RagStatus.SUCCESS
    # SystemMessage + USER + ASSISTANT + HumanMessage(context+question) = 4
    assert len(captured_messages) == 4
    from langchain_core.messages import HumanMessage, AIMessage
    assert isinstance(captured_messages[1], HumanMessage)
    assert "연차 어떻게?" in captured_messages[1].content
    assert isinstance(captured_messages[2], AIMessage)
    assert "HR 포털" in captured_messages[2].content


def test_generate_without_session_context_keeps_2_messages():
    from app.domain.rag.chain import RagChain
    chain = RagChain()
    captured = []
    def fake_invoke(messages):
        captured.extend(messages)
        return _mock_llm()
    with patch("app.domain.rag.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = fake_invoke
        chain.generate("질문", [_candidate()])
    assert len(captured) == 2  # SystemMessage + HumanMessage
