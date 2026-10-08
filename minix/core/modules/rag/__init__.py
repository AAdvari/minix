# MINIX RAG module — retrieval-augmented generation as a pluggable feature.
#
# Optional: it needs the `rag` extra (pip install "minix[rag]"). Nothing outside
# this package imports it, so a plain `pip install minix` never touches those
# dependencies.
#
# The package import stays light — the names below load on first access — so
# `import minix.core.modules.rag.<submodule>` (e.g. `controllers.schemas`) does
# not pull in the whole controller stack. Touching a name without the extra
# installed raises an ImportError that says what to install.
import importlib.util

__all__ = ["RagModule", "RagController", "RagConfig", "SmartChunker", "MetadataExtractor"]

# Third-party packages the RAG code imports at module load time.
_REQUIRED = (
    "langchain_core", "langchain_litellm", "langchain_qdrant",
    "langchain_text_splitters", "litellm", "qdrant_client", "psycopg",
)

_EXPORTS = {
    "RagModule": "minix.core.modules.rag.module",
    "RagController": "minix.core.modules.rag.controllers",
    "RagConfig": "minix.core.modules.rag.config",
    "SmartChunker": "minix.core.modules.rag.chunking",
    "MetadataExtractor": "minix.core.modules.rag.metadata_extractor",
}


def _require_extra() -> None:
    missing = [m for m in _REQUIRED if importlib.util.find_spec(m) is None]
    if missing:
        raise ImportError(
            "minix.core.modules.rag needs optional dependencies that are not "
            f"installed (missing: {', '.join(missing)}). "
            'Install them with: pip install "minix[rag]"'
        )


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    _require_extra()
    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
