import re

from app.common.exceptions import MaskingBlockedError
from app.core.config import settings

_ALWAYS_ON_PATTERNS: list[tuple[str, str]] = [
    (r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}", "[카드번호]"),
    (r"\d{6}[-\s]?\d{7}", "[주민번호]"),
]

_OPTIONAL_PATTERNS: list[tuple[str, str]] = [
    (r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}", "[전화번호]"),
    (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "[이메일]"),
]

_MASK_TOKENS = {"[주민번호]", "[카드번호]", "[전화번호]", "[이메일]"}


class SensitiveDataMasker:
    def __init__(
        self,
        patterns: list[tuple[str, str]] | None = None,
        enabled: bool | None = None,
    ) -> None:
        if enabled is None:
            enabled = settings.masking_enabled
        self._enabled = enabled

        if patterns is not None:
            self._patterns = patterns
        else:
            active = list(_ALWAYS_ON_PATTERNS)
            if settings.masking_phone_enabled:
                active.append(_OPTIONAL_PATTERNS[0])
            if settings.masking_email_enabled:
                active.append(_OPTIONAL_PATTERNS[1])
            self._patterns = active

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


masker = SensitiveDataMasker()
