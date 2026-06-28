from app.domain.chatbot.no_result_policy import should_precheck_general_chat


def test_greeting_should_precheck_general_chat():
    assert should_precheck_general_chat("안녕")


def test_common_knowledge_question_should_not_precheck_general_chat():
    assert not should_precheck_general_chat("아메리카노가뭐야?")


def test_company_question_should_not_precheck_general_chat():
    assert not should_precheck_general_chat("한화가 뭐야?")


def test_work_support_keyword_should_not_precheck_general_chat():
    assert not should_precheck_general_chat("권한 오류가 뭐야?")


def test_phone_number_lookup_should_not_precheck_general_chat():
    assert not should_precheck_general_chat("01048998954 누구야?")


def test_employee_lookup_keyword_should_not_precheck_general_chat():
    assert not should_precheck_general_chat("이 번호 조회해줘")


def test_employee_id_lookup_should_not_precheck_general_chat():
    assert not should_precheck_general_chat("sa002 누구야?")
    assert not should_precheck_general_chat("SA002는 누구야?")
