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


# ── StreamMasker: 토큰 스트림 마스킹 ──────────────────────────────────────────

from app.common.masking import (  # noqa: E402
    StreamMasker,
    _ALWAYS_ON_PATTERNS,
    _OPTIONAL_PATTERNS,
)


def _all_pattern_base() -> SensitiveDataMasker:
    return SensitiveDataMasker(
        patterns=list(_ALWAYS_ON_PATTERNS) + list(_OPTIONAL_PATTERNS), enabled=True
    )


def _stream(chunks: list[str], base: SensitiveDataMasker | None = None) -> str:
    sm = StreamMasker(base or _all_pattern_base())
    out = ""
    for c in chunks:
        out += sm.feed(c)
    out += sm.flush()
    return out


def test_stream_phone_split_across_chunks():
    assert _stream(["연락처 ", "010-", "1234", "-56", "78 끝"]) == "연락처 [전화번호] 끝"


def test_stream_ssn_split_across_chunks():
    assert _stream(["주민 ", "900101", "-", "1234567", " 끝"]) == "주민 [주민번호] 끝"


def test_stream_email_char_by_char():
    text = "메일 test@example.com 으로"
    assert _stream(list(text)) == "메일 [이메일] 으로"


def test_stream_no_sensitive_passthrough():
    chunks = ["안녕하세요 ", "무엇을 ", "도와드릴까요?"]
    assert _stream(chunks) == "안녕하세요 무엇을 도와드릴까요?"


def test_stream_matches_full_text_masking():
    base = _all_pattern_base()
    text = "카드 1234-5678-9012-3456 주민 900101-1234567 메일 a@b.com"
    streamed = _stream(list(text), base)
    assert streamed == base.mask(text)


def test_stream_disabled_passthrough():
    sm = StreamMasker(SensitiveDataMasker(enabled=False))
    assert sm.feed("010-1234-5678") + sm.flush() == "010-1234-5678"


def test_stream_card_at_very_end():
    # 패턴이 스트림 맨 끝에 걸쳐도 flush에서 마스킹된다.
    assert _stream(["번호 ", "1234-5678-", "9012-3456"]) == "번호 [카드번호]"
