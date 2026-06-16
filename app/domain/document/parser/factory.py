from fastapi import HTTPException, UploadFile

from .docx_parser import DocxParser
from .pdf_parser import PdfParser
from .txt_parser import TxtParser

_CONTENT_TYPE_MAP = {
    "application/pdf": PdfParser(),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxParser(),
    "text/plain": TxtParser(),
}
_EXTENSION_MAP = {
    ".pdf": PdfParser(),
    ".docx": DocxParser(),
    ".txt": TxtParser(),
}


def parse_upload_file(file: UploadFile) -> str:
    parser = _CONTENT_TYPE_MAP.get(file.content_type or "")

    if parser is None:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
        parser = _EXTENSION_MAP.get(ext)

    if parser is None:
        raise HTTPException(status_code=415, detail="지원하지 않는 파일 형식입니다. 허용: pdf, docx, txt")

    return parser.parse(file.file.read(), file.filename or "")


def parse_upload_pages(file: UploadFile) -> list[dict] | None:
    parser = _CONTENT_TYPE_MAP.get(file.content_type or "")

    if parser is None:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
        parser = _EXTENSION_MAP.get(ext)

    if parser is None:
        raise HTTPException(status_code=415, detail="지원하지 않는 파일 형식입니다. 허용: pdf, docx, txt")

    content = file.file.read()
    if hasattr(parser, "parse_pages"):
        return parser.parse_pages(content, file.filename or "")
    return None
