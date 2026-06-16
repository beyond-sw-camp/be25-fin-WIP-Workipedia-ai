import io

from pypdf import PdfReader

from .base import BaseParser


class PdfParser(BaseParser):
    def parse(self, file_bytes: bytes, filename: str = "") -> str:
        return "\n".join(page["text"] for page in self.parse_pages(file_bytes, filename))

    def parse_pages(self, file_bytes: bytes, filename: str = "") -> list[dict]:
        reader = PdfReader(io.BytesIO(file_bytes))
        return [
            {"page": idx + 1, "text": page.extract_text() or ""}
            for idx, page in enumerate(reader.pages)
        ]
