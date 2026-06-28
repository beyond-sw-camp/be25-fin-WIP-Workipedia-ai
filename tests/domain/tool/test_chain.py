import json
from unittest.mock import MagicMock, patch

import pytest

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.domain.rag.schemas import GeneratedAnswer, RagStatus
from tests.domain.tool.conftest import make_exec_result


@pytest.fixture
def chain():
    from app.domain.tool.chain import ToolResultChain
    return ToolResultChain()


def _llm_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.content = json.dumps(payload, ensure_ascii=False)
    return mock


def test_blocked_when_masking_raises(chain):
    with patch("app.domain.tool.chain.get_llm") as mock_llm, \
         patch("app.domain.tool.chain.masker") as mock_masker:
        mock_llm.return_value.invoke.return_value = _llm_response({"status": "ANSWER", "answer": "답변"})
        mock_masker.mask.side_effect = MaskingBlockedError("차단")
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)
    assert result.status == RagStatus.BLOCKED


def test_no_result_when_insufficient_result(chain):
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response({"status": "INSUFFICIENT_RESULT"})
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_success_with_valid_answer(chain):
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "홍길동은 개발팀 소속입니다."}
        )
        result = chain.generate("E001이 누구야?", make_exec_result(), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert isinstance(result.answer, GeneratedAnswer)
    assert result.answer.answer == "홍길동은 개발팀 소속입니다."
    assert result.answer.references == []


def test_tool_source_is_appended_to_llm_answer(chain):
    data = {
        "latitude": 37.5665,
        "longitude": 126.978,
        "temperature": 23.5,
        "humidity": 76,
        "windSpeed": 5.4,
        "weatherCode": 1,
        "source": "open-meteo",
    }
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "서울의 현재 기온은 23.5도입니다."}
        )
        result = chain.generate("서울 날씨 어때?", make_exec_result(data=data), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == "서울의 현재 기온은 23.5도입니다.\n\n[출처: open-meteo]"


def test_tool_source_is_not_duplicated(chain):
    data = {"source": "open-meteo", "temperature": 23.5}
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "서울의 현재 기온은 23.5도입니다.\n\n[출처: open-meteo]"}
        )
        result = chain.generate("서울 날씨 어때?", make_exec_result(data=data), custom_prompt=None)

    assert result.answer.answer == "서울의 현재 기온은 23.5도입니다.\n\n[출처: open-meteo]"


def test_retries_once_on_parse_failure(chain):
    bad = MagicMock()
    bad.content = "이건 JSON이 아님"
    good = _llm_response({"status": "ANSWER", "answer": "답변"})

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = [bad, good]
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert mock_llm.return_value.invoke.call_count == 2


def test_raises_provider_error_after_two_parse_failures(chain):
    bad = MagicMock()
    bad.content = "이건 JSON이 아님"

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = bad
        with pytest.raises(ProviderError, match="Tool 결과 응답 파싱 실패"):
            chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert mock_llm.return_value.invoke.call_count == 2


def test_raw_tool_result_passed_to_llm(chain):
    """Tool 결과 원문이 LLM 메시지에 전달되는지 확인."""
    exec_result = make_exec_result()
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "답변"}
        )
        chain.generate("질문", exec_result, custom_prompt=None)

    messages = mock_llm.return_value.invoke.call_args[0][0]
    import json
    raw_text = json.dumps(exec_result.data, ensure_ascii=False)
    assert raw_text in messages[1].content


def test_tool_prompt_allows_question_subject_label(chain):
    """질문에 포함된 지역/대상명을 답변 주어로 쓸 수 있다는 규칙을 전달한다."""
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "남극의 현재 기온은 -55.8도입니다."}
        )
        chain.generate("남극 날씨 어때?", make_exec_result(), custom_prompt=None)

    messages = mock_llm.return_value.invoke.call_args[0][0]
    assert "질문에 포함된 지역명, 대상명, 조건은 답변의 주어 또는 범위로 사용할 수 있습니다" in messages[0].content
    assert "수치와 상태 정보는 반드시 [Tool Result]에 있는 값만 사용하세요" in messages[0].content
    assert "[Question]\n남극 날씨 어때?" in messages[1].content


def test_answer_is_masked_before_returning(chain):
    """LLM 응답 답변에 마스킹이 적용되는지 확인."""
    with patch("app.domain.tool.chain.get_llm") as mock_llm, \
         patch("app.domain.tool.chain.masker") as mock_masker:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "홍길동 010-1234-5678"}
        )
        mock_masker.mask.return_value = "홍길동 [전화번호]"
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert result.answer.answer == "홍길동 [전화번호]"


def test_employee_lookup_result_uses_fixed_format(chain):
    data = {
        "matched": True,
        "matchType": "PHONE",
        "employee": {
            "employeeId": "SA001",
            "loginId": "jinhyuk.kim",
            "name": "김진혁",
            "departmentName": "AI플랫폼팀",
            "positionName": "매니저",
            "email": "jinhyuk.kim@hanwha.com",
            "phoneNumber": "010-4899-8954",
            "status": "ACTIVE",
        },
        "source": "사용자 본인 정보 조회",
    }

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        result = chain.generate("01048998954 누구야?", make_exec_result(data=data), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == (
        "해당 번호(010-4899-8954)는 **김진혁** 님(아이디: jinhyuk.kim)으로 조회됩니다.\n\n"
        "- 소속: AI플랫폼팀\n"
        "- 직급: 매니저\n"
        "- 사번: SA001\n"
        "- 이메일: jinhyuk.kim@hanwha.com\n\n"
        "[출처: 사용자 본인 정보 조회]"
    )
    mock_llm.assert_not_called()


def test_employee_lookup_not_matched_uses_fixed_message(chain):
    data = {
        "matched": False,
        "matchType": "PHONE",
        "employee": None,
        "source": "사용자 본인 정보 조회",
    }

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        result = chain.generate("00000000000 누구야?", make_exec_result(data=data), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == "조회되는 임직원 정보를 찾지 못했습니다.\n\n[출처: 사용자 본인 정보 조회]"
    mock_llm.assert_not_called()


def test_leave_balance_result_uses_fixed_format(chain):
    data = {
        "employee": {
            "employeeId": "SA001",
            "name": "김진혁",
            "departmentName": "AI플랫폼팀",
        },
        "year": 2026,
        "leave": {
            "grantedDays": 15.0,
            "carriedOverDays": 0.0,
            "adjustedDays": 0.0,
            "usedDays": 2.0,
            "scheduledDays": 0.0,
            "pendingDays": 0.0,
            "remainingDays": 13.0,
            "expiresOn": "2026-12-31",
        },
        "source": "연차 잔여량 조회",
        "asOfDate": "2026-06-28",
    }

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        result = chain.generate("나 연차 몇개 남았어?", make_exec_result(data=data), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == (
        "**김진혁** 님의 2026년 잔여 연차는 **13일**입니다.\n\n"
        "- 소속: AI플랫폼팀\n"
        "- 사번: SA001\n"
        "- 부여 연차: 15일\n"
        "- 이월 연차: 0일\n"
        "- 조정 연차: 0일\n"
        "- 사용 연차: 2일\n"
        "- 예정 연차: 0일\n"
        "- 승인 대기 연차: 0일\n"
        "- 만료일: 2026-12-31\n"
        "- 기준일: 2026-06-28\n\n"
        "[출처: 연차 잔여량 조회]"
    )
    mock_llm.assert_not_called()
