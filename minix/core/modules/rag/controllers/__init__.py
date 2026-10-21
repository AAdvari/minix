# RAG module controller exports. Lazy so importing `controllers.schemas` does
# not pull in optional LangChain/Qdrant runtime dependencies.

__all__ = ["RagController"]


def __getattr__(name: str):
    if name == "RagController":
        from minix.core.modules.rag.controllers.rag_controller import RagController
        return RagController
    raise AttributeError(name)
