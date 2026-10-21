# Landing AI document extraction backend for structured documents.
import os
from pathlib import Path

from minix.core.modules.rag.document_processor.base import BaseDocumentProcessor


class LandingAIProcessor(BaseDocumentProcessor):

    def __init__(self, api_key: str | None = None, extract_tables: bool = True):
        self._api_key = api_key or os.getenv("LANDINGAI_API_KEY")
        self._extract_tables = extract_tables
        if not self._api_key:
            raise ValueError(
                "Landing AI API key is required. "
                "Pass api_key= or set LANDINGAI_API_KEY in your environment."
            )

    def extract(self, file_path: str | Path) -> str:
        try:
            from landingai.data_management.client import LandingAIClient
        except ImportError as e:
            raise ImportError(
                "The Landing AI document backend needs the `landingai` package: "
                "pip install landingai"
            ) from e
        file_path = Path(file_path)
        client = LandingAIClient(api_key=self._api_key)
        with open(file_path, "rb") as f:
            result = client.extract_document(file=f, file_name=file_path.name)
        return self._result_to_text(result)

    def _result_to_text(self, result) -> str:
        parts = []
        for block in result.get("blocks", []):
            block_type = block.get("type", "")
            if block_type == "text":
                content = block.get("content", "").strip()
                if content:
                    parts.append(content)
            elif block_type == "table" and self._extract_tables:
                rows = block.get("rows", [])
                for row in rows:
                    cells = [cell.get("content", "") for cell in row]
                    parts.append("\t".join(cells))
        return "\n\n".join(parts)
