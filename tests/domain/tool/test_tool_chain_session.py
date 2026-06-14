from unittest.mock import MagicMock, patch
import json
from app.domain.chatbot.schemas import SessionMessage
from app.domain.tool.schemas import ToolExecutionResult
from app.domain.rag.schemas import RagStatus


def _result():
    return ToolExecutionResult(tool_id="t1", data={"value": "100"})


def test_tool_chain_with_session_inserts_history():
    from app.domain.tool.chain import ToolResultChain
    chain = ToolResultChain()
    context = [SessionMessage(message_id=1, sender_type="USER", content="잔여 연차?")]
    captured = []
    resp = MagicMock()
    resp.content = json.dumps({"status": "ANSWER", "answer": "10일"})

    def fake_invoke(messages):
        captured.extend(messages)
        return resp

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = fake_invoke
        result = chain.generate("잔여 연차 알려줘", _result(), None, session_context=context)
    assert result.status == RagStatus.SUCCESS
    # SystemMessage + HumanMessage(session USER) + HumanMessage(ToolResult+Question) = 3
    assert len(captured) == 3


def test_tool_chain_without_session_keeps_2_messages():
    from app.domain.tool.chain import ToolResultChain
    chain = ToolResultChain()
    captured = []
    resp = MagicMock()
    resp.content = json.dumps({"status": "ANSWER", "answer": "10일"})

    def fake_invoke(messages):
        captured.extend(messages)
        return resp

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = fake_invoke
        chain.generate("잔여 연차?", _result(), None)
    assert len(captured) == 2
