import io

from pypdf import PdfReader

from .base import BaseParser


class PdfParser(BaseParser):
    def parse(self, file_bytes: bytes, filename: str = "") -> str:
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
