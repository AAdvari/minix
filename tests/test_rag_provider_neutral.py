"""Every model call in the RAG module goes through LiteLLM, not a single vendor.

Embeddings, metadata extraction, document transcription and LLM chunking used to
construct an OpenAI client directly, so the module could not run without an
OpenAI key even when the answer model came from another provider. These tests
point LiteLLM at an in-process OpenAI-compatible server (the same shape Ollama,
vLLM, LM Studio, Azure gateways and others expose) and check that each call
reaches it, with the right request, using only the configured model name — no
vendor SDK, no real provider, no credits.
"""
import json
import pathlib
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("litellm")
pytest.importorskip("langchain_core")

from minix.core.modules.rag.config import RagConfig  # noqa: E402
from minix.core.modules.rag.embeddings import LiteLLMEmbeddings  # noqa: E402
from minix.core.modules.rag.llm_factory import make_llm_client  # noqa: E402


class _FakeProvider:
    """Records every request; answers embeddings and chat completions."""

    def __init__(self):
        self.requests: list[dict] = []
        self.chat_reply = "fake reply"
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({
                    "path": self.path, "body": body,
                    "auth": self.headers.get("Authorization"),
                })
                if self.path.endswith("/embeddings"):
                    texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
                    # Deliberately out of order: callers must sort by `index`.
                    data = [
                        {"object": "embedding", "index": i,
                         "embedding": [float(len(texts[i])), float(i), 1.0]}
                        for i in reversed(range(len(texts)))
                    ]
                    reply = {"object": "list", "model": body["model"], "data": data,
                             "usage": {"prompt_tokens": 1, "total_tokens": 1}}
                else:
                    reply = {
                        "id": "chatcmpl-fake", "object": "chat.completion", "model": body["model"],
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": outer.chat_reply}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                payload = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_port}/v1"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()

    def last(self) -> dict:
        return self.requests[-1]


@pytest.fixture()
def provider(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setenv("OPENAI_API_BASE", fake.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    yield fake
    fake.close()


# ── embeddings ───────────────────────────────────────────────────────────────

def test_embeddings_batch_and_keep_input_order(provider):
    emb = LiteLLMEmbeddings("text-embedding-3-small", dimensions=3, batch_size=2)
    vectors = emb.embed_documents(["a", "bb", "ccc"])
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]     # one vector per text, in order
    assert [len(r["body"]["input"]) for r in provider.requests] == [2, 1]
    assert all(r["path"] == "/v1/embeddings" and r["auth"] == "Bearer fake-key"
               for r in provider.requests)


def test_embeddings_send_dimensions_only_when_asked(provider):
    LiteLLMEmbeddings("text-embedding-3-small", dimensions=3).embed_query("x")
    assert provider.last()["body"]["dimensions"] == 3
    LiteLLMEmbeddings("text-embedding-3-small", dimensions=None).embed_query("x")
    assert "dimensions" not in provider.last()["body"]


def test_embeddings_work_with_a_custom_model_name(provider):
    vector = LiteLLMEmbeddings("openai/my-local-embedder").embed_query("hello")
    assert vector == [5.0, 0.0, 1.0]
    assert provider.last()["body"]["model"] == "my-local-embedder"


def test_embeddings_explain_a_model_that_rejects_dimensions(provider):
    with pytest.raises(ValueError, match="RAG_EMBEDDING_SEND_DIMENSIONS=false"):
        LiteLLMEmbeddings("openai/my-local-embedder", dimensions=3).embed_query("hello")


def test_embedding_settings_flow_from_config(provider, monkeypatch):
    from minix.core.modules.rag import qdrant_ops

    monkeypatch.setattr(RagConfig, "EMBEDDING_MODEL", "openai/other-embedder")
    monkeypatch.setattr(RagConfig, "EMBEDDING_DIMENSION", 7)
    monkeypatch.setattr(RagConfig, "EMBEDDING_SEND_DIMENSIONS", False)
    qdrant_ops.get_embeddings.cache_clear()
    try:
        emb = qdrant_ops.get_embeddings()
        assert (emb.model, emb.dimensions) == ("openai/other-embedder", None)
        monkeypatch.setattr(RagConfig, "EMBEDDING_SEND_DIMENSIONS", True)
        qdrant_ops.get_embeddings.cache_clear()
        assert qdrant_ops.get_embeddings().dimensions == 7
    finally:
        qdrant_ops.get_embeddings.cache_clear()


# ── raw chat completions ─────────────────────────────────────────────────────

def test_llm_client_speaks_the_openai_call_shape_over_litellm(provider):
    response = make_llm_client().chat.completions.create(
        model="openai/any-chat-model",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert response.choices[0].message.content == "fake reply"
    assert provider.last()["path"] == "/v1/chat/completions"
    assert provider.last()["body"]["model"] == "any-chat-model"


def test_metadata_extraction_needs_no_vendor_sdk(provider, monkeypatch):
    from minix.core.modules.rag.metadata_extractor import MetadataExtractor

    provider.chat_reply = '{"title": "Supply Agreement", "authors": ["A", "B"], "summary": null}'
    monkeypatch.setattr(RagConfig, "DOCUMENT_PROCESSOR_MODEL", "openai/extractor")
    meta = MetadataExtractor().extract("Plain document text about a supply agreement.")
    assert meta["title"] == "Supply Agreement"
    assert meta["authors"] == "A, B"
    assert provider.last()["body"]["model"] == "extractor"


def test_document_transcription_sends_the_image_to_the_configured_model(provider, monkeypatch):
    pil = pytest.importorskip("PIL.Image")
    from minix.core.modules.rag.document_processor.gpt_processor import GPTProcessor

    provider.chat_reply = "transcribed text"
    monkeypatch.setattr(RagConfig, "DOCUMENT_PROCESSOR_MODEL", "openai/vision-model")
    text = GPTProcessor()._call_vision_api(pil.new("RGB", (4, 4), "white"))
    assert text == "transcribed text"
    parts = provider.last()["body"]["messages"][0]["content"]
    assert any(p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,")
               for p in parts)
    assert provider.last()["body"]["model"] == "vision-model"


def test_llm_chunking_builds_without_any_vendor_key(monkeypatch):
    from minix.core.modules.rag.chunking.smart_chunker import _LLMStrategy

    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    strategy = _LLMStrategy(chunk_size=800, chunk_overlap=100, instruction="split by topic")
    assert hasattr(strategy._client.chat.completions, "create")


def test_no_vendor_sdk_is_imported_by_the_rag_package():
    """The guard that keeps it neutral: a direct `openai` / `langchain_openai`
    import would tie the module back to one provider."""
    package = pathlib.Path(__file__).resolve().parents[1] / "minix" / "core" / "modules" / "rag"
    vendor = re.compile(r"^\s*(?:from|import)\s+(openai|langchain_openai|anthropic|cohere)\b", re.M)
    offenders = [
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if "__pycache__" not in path.parts and vendor.search(path.read_text())
    ]
    assert not offenders, f"direct vendor SDK imports: {offenders}"
