from abc import ABC, abstractmethod


class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str = "") -> str:
        pass
