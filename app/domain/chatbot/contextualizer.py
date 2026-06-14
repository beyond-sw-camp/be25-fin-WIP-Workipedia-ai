from langchain_core.messages import HumanMessage, SystemMessage

from app.common.exceptions import ProviderError
from app.core.config import settings
from app.domain.chatbot.schemas import SessionMessage
from app.infra.llm.factory import get_llm

_SYSTEM_PROMPT = (
    "아래 대화 기록을 참고해 현재 질문을 검색에 쓸 수 있는 독립된 문장으로 재작성해. "
    "재작성한 질문만 반환하고 다른 텍스트는 포함하지 마."
)


def _build_history(context: list[SessionMessage]) -> str:
    lines = []
    for msg in context:
        role = "사용자" if msg.sender_type == "USER" else "어시스턴트"
        lines.append(f"{role}: {msg.content}")
    return "\n".join(lines)


_MAX_RETRIEVAL_QUERY_LEN = 500


def _clean_response(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = [l for l in lines[1:] if l.strip() != "```"]
        stripped = "\n".join(inner).strip()
    return stripped.splitlines()[0].strip() if stripped else ""


def contextualize(question: str, context: list[SessionMessage]) -> str:
    if not context:
        return question

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"[대화 기록]\n{_build_history(context)}\n\n[현재 질문]\n{question}"),
    ]
    # ProviderError는 호출자에게 전파한다
    response = get_llm(request_timeout=settings.contextualize_llm_timeout).invoke(messages)

    raw = response.content
    if isinstance(raw, list):
        raw = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)

    result = _clean_response(str(raw))

    if not result or len(result) > _MAX_RETRIEVAL_QUERY_LEN:
        return question
    return result
