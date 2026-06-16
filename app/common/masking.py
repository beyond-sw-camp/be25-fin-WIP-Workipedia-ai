import re

from app.common.exceptions import MaskingBlockedError
from app.core.config import MASKING_EMAIL_ENABLED, MASKING_ENABLED, MASKING_PHONE_ENABLED

_ALWAYS_ON_PATTERNS: list[tuple[str, str]] = [
    (r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}", "[카드번호]"),  # card BEFORE SSN
    (r"\d{6}[-\s]?\d{7}", "[주민번호]"),
]
_OPTIONAL_PATTERNS: list[tuple[str, str]] = [
    (r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}", "[전화번호]"),
    (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "[이메일]"),
]
_MASK_TOKENS = {"[주민번호]", "[카드번호]", "[전화번호]", "[이메일]"}


class SensitiveDataMasker:
    def __init__(self, patterns: list[tuple[str, str]] | None = None, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = MASKING_ENABLED
        self._enabled = enabled
        if patterns is not None:
            self._patterns = patterns
        else:
            active = list(_ALWAYS_ON_PATTERNS)
            if MASKING_PHONE_ENABLED:
                active.append(_OPTIONAL_PATTERNS[0])
            if MASKING_EMAIL_ENABLED:
                active.append(_OPTIONAL_PATTERNS[1])
            self._patterns = active

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def mask(self, text: str) -> str:
        if not self._enabled or not text:
            return text
        result = text
        try:
            for pattern, token in self._patterns:
                def _replace(m: re.Match, _token: str = token) -> str:
                    matched = m.group()
                    if matched in _MASK_TOKENS:
                        return matched
                    return _token
                result = re.sub(pattern, _replace, result)
        except Exception as exc:
            raise MaskingBlockedError(f"마스킹 처리 중 오류: {exc}") from exc
        return result


class StreamMasker:
    """토큰 스트림을 안전하게 마스킹한다.

    민감정보 패턴은 청크 경계에 걸쳐 분리되어 도착할 수 있으므로, 패턴이 완성될
    만큼의 꼬리(`_LOOKBACK`)를 버퍼에 남겨둔다. 경계에 패턴이 걸치지 않을 때만
    안전한 앞부분을 마스킹하여 flush하고, 걸쳐 있으면 다음 청크를 기다린다.
    """

    _LOOKBACK = 24  # 가장 긴 패턴(카드 16자리 + 구분자 ≈ 19자) 이상으로 둔다.

    def __init__(self, base: SensitiveDataMasker | None = None) -> None:
        self._base = base or masker
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        if not self._base.is_enabled:
            return chunk
        self._buffer += chunk
        if len(self._buffer) <= self._LOOKBACK:
            return ""
        tail = self._buffer[-self._LOOKBACK:]
        masked_full = self._base.mask(self._buffer)
        masked_tail = self._base.mask(tail)
        # 경계에 패턴이 걸치면 전체 마스킹 결과의 끝이 꼬리 단독 마스킹과 달라진다.
        # 이때는 flush하지 않고 다음 청크를 기다린다. (패턴 길이 < _LOOKBACK 이므로
        # flush되는 앞부분은 미래 입력으로 패턴이 될 수 없어 안전하다.)
        if masked_full.endswith(masked_tail):
            self._buffer = tail
            return masked_full[: len(masked_full) - len(masked_tail)]
        return ""

    def flush(self) -> str:
        if not self._buffer:
            return ""
        out = self._buffer if not self._base.is_enabled else self._base.mask(self._buffer)
        self._buffer = ""
        return out


masker = SensitiveDataMasker()

# Tool 결과는 외부 API/DB에서 오므로 전화번호·이메일을 포함한 전체 패턴을 적용한다.
tool_masker = SensitiveDataMasker(patterns=list(_ALWAYS_ON_PATTERNS) + list(_OPTIONAL_PATTERNS))


def masker_for(source_type: str) -> SensitiveDataMasker:
    """source_type에 맞는 마스커를 반환한다.
    WORKI는 전화번호·이메일 포함, 나머지는 주민번호·카드번호만 마스킹한다.
    """
    if source_type == "WORKI":
        return SensitiveDataMasker(patterns=list(_ALWAYS_ON_PATTERNS) + list(_OPTIONAL_PATTERNS))
    return SensitiveDataMasker(patterns=list(_ALWAYS_ON_PATTERNS))
