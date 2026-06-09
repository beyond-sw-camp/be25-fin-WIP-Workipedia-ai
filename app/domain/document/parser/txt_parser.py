from .base import BaseParser


class TxtParser(BaseParser):
    def parse(self, file_bytes: bytes, filename: str = "") -> str:
        return file_bytes.decode("utf-8", errors="ignore")
