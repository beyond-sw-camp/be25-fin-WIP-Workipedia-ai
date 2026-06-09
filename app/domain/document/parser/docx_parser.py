import io

from docx import Document

from .base import BaseParser


class DocxParser(BaseParser):
    def parse(self, file_bytes: bytes, filename: str = "") -> str:
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
