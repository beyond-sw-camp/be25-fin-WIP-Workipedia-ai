from app.domain.rag.schemas import RerankedCandidate

_CUSTOM_PROMPT_SUFFIX = "\n\n[추가 지침 — 기본 규칙과 충돌하면 기본 규칙을 우선합니다]\n"

BASE_PROMPT = """당신은 Workipedia의 사내 지식 챗봇입니다.

[기본 규칙 — 추가 지침보다 항상 우선합니다]
1. 반드시 아래 [Context]에 명시된 내용만 사용하고, 추측하거나 외부 지식을 사용하지 마세요.
2. [Context]에 관련 내용이 없으면 status를 "INSUFFICIENT_CONTEXT"로 반환하세요.
3. 답변에 사용한 chunk의 ID([Context]의 [ID: ...])를 cited_ids에 모두 포함하세요.
4. 한국어로 간결하게 답하세요.

반드시 다음 JSON 형식 중 하나로만 응답하세요. JSON 외 다른 텍스트는 포함하지 마세요.
{"status":"ANSWER","answer":"답변 텍스트","cited_ids":["MANUAL:1:0"]}
{"status":"INSUFFICIENT_CONTEXT","answer":null,"cited_ids":[]}"""

TOOL_BASE_PROMPT = """당신은 Workipedia의 사내 지식 챗봇입니다.

[기본 규칙 — 추가 지침보다 항상 우선합니다]
1. 반드시 아래 [Tool Result]에 있는 정보만 사용하고, 추측하거나 외부 지식을 사용하지 마세요.
2. [Tool Result]로 답변할 수 없으면 status를 "INSUFFICIENT_RESULT"로 반환하세요.
3. 한국어로 간결하게 답하세요.

반드시 다음 JSON 형식 중 하나로만 응답하세요. JSON 외 다른 텍스트는 포함하지 마세요.
{"status":"ANSWER","answer":"답변 텍스트"}
{"status":"INSUFFICIENT_RESULT"}"""


ANSWER_STREAM_PROMPT = """당신은 Workipedia의 사내 지식 챗봇입니다.

[기본 규칙 — 추가 지침보다 항상 우선합니다]
1. 반드시 아래 [Context]에 명시된 내용만 근거로 답하고, 추측하거나 외부 지식을 사용하지 마세요.
2. 한국어로 간결하게 답하세요.
3. JSON이나 출처 표기 없이, 답변 본문만 자연스러운 문장으로 작성하세요."""


def build_system_prompt(custom_prompt: str | None) -> str:
    if custom_prompt:
        return f"{BASE_PROMPT}{_CUSTOM_PROMPT_SUFFIX}{custom_prompt}"
    return BASE_PROMPT


def build_tool_system_prompt(custom_prompt: str | None) -> str:
    if custom_prompt:
        return f"{TOOL_BASE_PROMPT}{_CUSTOM_PROMPT_SUFFIX}{custom_prompt}"
    return TOOL_BASE_PROMPT


def build_answer_stream_prompt(custom_prompt: str | None) -> str:
    if custom_prompt:
        return f"{ANSWER_STREAM_PROMPT}{_CUSTOM_PROMPT_SUFFIX}{custom_prompt}"
    return ANSWER_STREAM_PROMPT


def build_context(candidates: list[RerankedCandidate]) -> str:
    parts = [f"[ID: {c.candidate_id}]\n{c.text}" for c in candidates]
    return "\n\n".join(parts)
