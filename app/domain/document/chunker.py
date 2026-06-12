from langchain.text_splitter import RecursiveCharacterTextSplitter


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    # separators 순서: 단락 → 줄 → 한국어 마침표 → 영어 마침표 → 공백 → 문자 단위
    # RecursiveCharacterTextSplitter는 앞선 구분자로 자를 수 없을 때만 다음 구분자로 내려간다
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )
    return splitter.split_text(text)
