import pytest

from app.common.exceptions import MaskingBlockedError
from app.common.masking import SensitiveDataMasker


def test_ssn_with_dash():
    m = SensitiveDataMasker()
    assert m.mask("주민번호는 921203-1234567입니다.") == "주민번호는 [주민번호]입니다."


def test_ssn_with_space():
    m = SensitiveDataMasker()
    assert m.mask("주민번호는 921203 1234567입니다.") == "주민번호는 [주민번호]입니다."


def test_ssn_no_separator():
    m = SensitiveDataMasker()
    assert m.mask("9212031234567") == "[주민번호]"


def test_card_number_with_dash():
    m = SensitiveDataMasker()
    assert m.mask("카드번호 1234-5678-9012-3456") == "카드번호 [카드번호]"


def test_card_number_no_separator():
    m = SensitiveDataMasker()
    assert m.mask("1234567890123456") == "[카드번호]"


def test_no_sensitive_data():
    m = SensitiveDataMasker()
    assert m.mask("일반 텍스트입니다.") == "일반 텍스트입니다."


def test_empty_string():
    m = SensitiveDataMasker()
    assert m.mask("") == ""


def test_masking_disabled():
    m = SensitiveDataMasker(enabled=False)
    assert m.mask("921203-1234567") == "921203-1234567"


def test_no_double_masking():
    m = SensitiveDataMasker()
    assert m.mask("[주민번호] 입니다.") == "[주민번호] 입니다."


def test_blocked_on_regex_error():
    m = SensitiveDataMasker(patterns=[("(invalid[", "[X]")])
    with pytest.raises(MaskingBlockedError):
        m.mask("텍스트")


def test_multiple_sensitive_in_one_text():
    m = SensitiveDataMasker()
    result = m.mask("주민번호 921203-1234567, 카드 1234-5678-9012-3456")
    assert result == "주민번호 [주민번호], 카드 [카드번호]"


def test_phone_disabled_by_default():
    m = SensitiveDataMasker()
    text = "전화 010-1234-5678"
    assert m.mask(text) == text  # 기본값 masking_phone_enabled=False


def test_phone_enabled_explicitly():
    phone_pattern = (r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}", "[전화번호]")
    m = SensitiveDataMasker(patterns=[phone_pattern])
    assert m.mask("010-1234-5678") == "[전화번호]"


def test_ssn_space_separator():
    m = SensitiveDataMasker()
    assert m.mask("번호: 921203 1111111") == "번호: [주민번호]"
