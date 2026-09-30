# Abstract base class for document text extraction backends.
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class BaseDocumentProcessor(ABC):

    @abstractmethod
    def extract(self, file_path: str | Path) -> str:
        ...

    def clean(self, text: str, post_process: Callable[[str], str] | None = None) -> str:
        cleaned = self._standard_clean(text)
        if post_process is not None:
            cleaned = post_process(cleaned)
        return cleaned

    def process(self, file_path: str | Path, post_process: Callable[[str], str] | None = None) -> str:
        raw = self.extract(file_path)
        return self.clean(raw, post_process=post_process)

    def _standard_clean(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\f", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.rstrip() for line in text.splitlines())
        return text.strip()
