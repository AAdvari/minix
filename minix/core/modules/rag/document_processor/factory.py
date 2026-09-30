# Factory function to instantiate the correct document processor by provider name.
from minix.core.modules.rag.document_processor.base import BaseDocumentProcessor


def get_processor(provider: str, **kwargs) -> BaseDocumentProcessor:
    match provider.lower():
        case "gpt":
            from minix.core.modules.rag.document_processor.gpt_processor import GPTProcessor
            return GPTProcessor(**kwargs)
        case "landingai":
            from minix.core.modules.rag.document_processor.landingai_processor import LandingAIProcessor
            return LandingAIProcessor(**kwargs)
        case _:
            raise ValueError(
                f"Unknown provider: '{provider}'. Available: 'gpt', 'landingai'"
            )
