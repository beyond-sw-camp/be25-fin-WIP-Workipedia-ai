import chromadb
from chromadb import Collection

from app.core.config import settings


class ChromaStore:
    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(path=settings.chroma_persist_path)

    def get_collection(self, name: str = settings.chroma_collection_name) -> Collection:
        return self._client.get_or_create_collection(name)


chroma_store = ChromaStore()
