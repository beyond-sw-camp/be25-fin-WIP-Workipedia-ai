import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.domain.chatbot.schemas import SessionMessage
from pydantic import BaseModel, model_validator

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import masker
from app.core.config import settings
from app.domain.rag.prompt import build_tool_system_prompt
from app.domain.rag.schemas import GeneratedAnswer, RagResult, RagStatus
from app.domain.tool.schemas import ToolExecutionResult
from app.infra.llm.factory import get_llm


class _LLMAnswerSchema(BaseModel):
    status: Literal["ANSWER", "INSUFFICIENT_RESULT"]
    answer: str | None = None

    @model_validator(mode="after")
    def _answer_required(self) -> "_LLMAnswerSchema":
        if self.status == "ANSWER" and not (self.answer or "").strip():
            raise ValueError("ANSWER 상태에서 answer는 비어 있을 수 없습니다.")
        return self


def _extract_text(response) -> str:
    content = response.content
    if isinstance(content, list):
        text = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    else:
        text = str(content)
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        return "\n".join(l for l in lines[1:] if l.strip() != "```")
    return stripped


def _format_employee_lookup_result(data) -> str | None:
    if not isinstance(data, dict):
        return None

    source = str(data.get("source") or "임직원 정보 조회").strip()
    if data.get("matched") is False:
        return f"조회되는 임직원 정보를 찾지 못했습니다.\n\n[출처: {source}]"

    employee = data.get("employee")
    if not isinstance(employee, dict):
        return None

    name = str(employee.get("name") or "").strip()
    if not name:
        return None

    phone_number = str(employee.get("phoneNumber") or "").strip()
    login_id = str(employee.get("loginId") or "").strip()
    department = str(employee.get("departmentName") or "").strip()
    position = str(employee.get("positionName") or "").strip()
    employee_id = str(employee.get("employeeId") or "").strip()
    email = str(employee.get("email") or "").strip()

    subject = f"해당 번호({phone_number})" if phone_number else "해당 임직원"
    login_text = f"(아이디: {login_id})" if login_id else ""
    lines = [
        f"{subject}는 **{name}** 님{login_text}으로 조회됩니다.",
        "",
    ]
    if department:
        lines.append(f"- 소속: {department}")
    if position:
        lines.append(f"- 직급: {position}")
    if employee_id:
        lines.append(f"- 사번: {employee_id}")
    if email:
        lines.append(f"- 이메일: {email}")
    lines.extend(["", f"[출처: {source}]"])
    return "\n".join(lines)


def _format_number(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_leave_balance_result(data) -> str | None:
    if not isinstance(data, dict):
        return None

    leave = data.get("leave")
    employee = data.get("employee")
    if not isinstance(leave, dict) or not isinstance(employee, dict):
        return None

    remaining_days = leave.get("remainingDays")
    if remaining_days is None:
        return None

    name = str(employee.get("name") or "").strip()
    employee_id = str(employee.get("employeeId") or "").strip()
    department = str(employee.get("departmentName") or "").strip()
    source = str(data.get("source") or "연차 잔여량 조회").strip()
    year = data.get("year")
    as_of_date = str(data.get("asOfDate") or "").strip()

    subject = f"**{name}** 님" if name else "조회 대상자"
    year_text = f"{year}년 " if year is not None else ""
    lines = [
        f"{subject}의 {year_text}잔여 연차는 **{_format_number(remaining_days)}일**입니다.",
        "",
    ]
    if department:
        lines.append(f"- 소속: {department}")
    if employee_id:
        lines.append(f"- 사번: {employee_id}")
    for label, key in (
        ("부여 연차", "grantedDays"),
        ("이월 연차", "carriedOverDays"),
        ("조정 연차", "adjustedDays"),
        ("사용 연차", "usedDays"),
        ("예정 연차", "scheduledDays"),
        ("승인 대기 연차", "pendingDays"),
    ):
        value = leave.get(key)
        if value is not None:
            lines.append(f"- {label}: {_format_number(value)}일")
    expires_on = str(leave.get("expiresOn") or "").strip()
    if expires_on:
        lines.append(f"- 만료일: {expires_on}")
    if as_of_date:
        lines.append(f"- 기준일: {as_of_date}")
    lines.extend(["", f"[출처: {source}]"])
    return "\n".join(lines)


def _extract_tool_source(data) -> str | None:
    if not isinstance(data, dict):
        return None
    source = str(data.get("source") or "").strip()
    return source or None


def _append_tool_source(answer: str, data) -> str:
    if "[출처:" in answer:
        return answer
    source = _extract_tool_source(data)
    if source is None:
        return answer
    return f"{answer.rstrip()}\n\n[출처: {source}]"


class ToolResultChain:
    def generate(
        self,
        query: str,
        result: ToolExecutionResult,
        custom_prompt: str | None,
        session_context: list[SessionMessage] | None = None,
    ) -> RagResult:
        fixed_answer = _format_leave_balance_result(result.data) or _format_employee_lookup_result(result.data)
        if fixed_answer is not None:
            try:
                masked_answer = masker.mask(fixed_answer)
            except MaskingBlockedError:
                return RagResult(status=RagStatus.BLOCKED)
            return RagResult(
                status=RagStatus.SUCCESS,
                answer=GeneratedAnswer(answer=masked_answer, references=[]),
            )

        tool_text = json.dumps(result.data, ensure_ascii=False)

        history_messages = []
        for msg in (session_context or []):
            if msg.sender_type == "USER":
                history_messages.append(HumanMessage(content=msg.content))
            else:
                history_messages.append(AIMessage(content=msg.content))

        messages = [
            SystemMessage(content=build_tool_system_prompt(custom_prompt)),
            *history_messages,
            HumanMessage(content=f"[Tool Result]\n{tool_text}\n\n[Question]\n{query}"),
        ]

        last_error = ""
        parsed = None
        for attempt in range(2):
            try:
                response = get_llm(
                    request_timeout=settings.tool_http_timeout,
                    max_retries=0,
                ).invoke(messages)
                parsed = _LLMAnswerSchema.model_validate(json.loads(_extract_text(response)))
                break
            except ProviderError:
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt == 1:
                    raise ProviderError("llm", f"Tool 결과 응답 파싱 실패: {last_error}") from exc

        if parsed.status == "INSUFFICIENT_RESULT":
            return RagResult(status=RagStatus.NO_RESULT)

        answer = _append_tool_source(parsed.answer, result.data)

        try:
            masked_answer = masker.mask(answer)
        except MaskingBlockedError:
            return RagResult(status=RagStatus.BLOCKED)
        return RagResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer=masked_answer, references=[]),
        )
