# Single place the LLM clients are constructed — every model call in the RAG
# module goes through LiteLLM, so any provider it supports (OpenAI, Azure,
# Anthropic, Bedrock, Ollama, …) works by changing a model name.
#
# Chat LLM (answers, reranking, grounding judge):
#
# F-3: there were two `ChatLiteLLM(...)` constructions — `rag_chain._make_llm`
# and `groundedness._llm` — and they were deliberate duplicates, with
# `groundedness.py` carrying the comment "Mirror rag_chain's LLM construction
# without importing rag_chain" to dodge a circular import. Neither set a timeout,
# a token ceiling, or a retry bound, so a provider that accepted a connection and
# then stalled would hang the request thread indefinitely. Duplicated
# construction also meant any fix had to be applied twice or it silently missed
# one path.
#
# B-2 made that second path load-bearing: the LLM judge now runs on every guarded
# query, so the un-timed constructor was on the hot path for the primary
# groundedness gate rather than a disabled option.
#
# This module imports only the config and langchain, so both callers can depend on
# it without the cycle that motivated the duplication.
from __future__ import annotations

from types import SimpleNamespace

import litellm
from langchain_litellm import ChatLiteLLM

from minix.core.modules.rag.config import RagConfig

# Per-call bounds for the raw completion client below (document transcription,
# metadata extraction, LLM chunking). They mirror the defaults the OpenAI SDK
# applied when these calls used it directly: a generous timeout, because a PDF
# page transcription legitimately takes a while, and two retries.
_CLIENT_TIMEOUT_SECONDS = 600
_CLIENT_MAX_RETRIES = 2


def make_chat_llm(**overrides) -> ChatLiteLLM:
    """Construct the chat LLM with the configured bounds applied.

    `timeout` and `max_tokens` are only passed when configured, so leaving either
    unset preserves the provider default rather than imposing one here.
    """
    kwargs: dict = {"model": RagConfig.LLM_MODEL, "streaming": False}
    if RagConfig.LLM_TEMPERATURE is not None:
        kwargs["temperature"] = RagConfig.LLM_TEMPERATURE
    if RagConfig.LLM_TIMEOUT_SECONDS is not None:
        # `request_timeout`, NOT `timeout`. ChatLiteLLM's field is
        # `request_timeout`, and it accepts unknown kwargs without complaining —
        # so passing `timeout=` sets nothing and raises nothing, which is exactly
        # the silent no-op this whole change exists to remove. The test asserts
        # the value lands on the constructed client rather than that the config
        # key exists.
        kwargs["request_timeout"] = RagConfig.LLM_TIMEOUT_SECONDS
    if RagConfig.LLM_MAX_TOKENS is not None:
        kwargs["max_tokens"] = RagConfig.LLM_MAX_TOKENS
    kwargs.update(overrides)
    return ChatLiteLLM(**kwargs)


class _Completions:
    def create(self, **kwargs):
        kwargs.setdefault("timeout", _CLIENT_TIMEOUT_SECONDS)
        kwargs.setdefault("num_retries", _CLIENT_MAX_RETRIES)
        return litellm.completion(**kwargs)


def make_llm_client() -> SimpleNamespace:
    """A provider-neutral client for raw chat completions.

    It exposes the OpenAI-SDK call shape — ``client.chat.completions.create(
    model=..., messages=[...], response_format=...)`` returning an object with
    ``.choices[0].message.content`` — but routes every call through LiteLLM, so
    the ``model`` can name any supported provider. API keys are read by LiteLLM
    from the provider's standard environment variable (OPENAI_API_KEY,
    ANTHROPIC_API_KEY, AZURE_API_KEY, …). Used where the code needs a plain
    completion rather than a LangChain runnable; tests replace the client on the
    object that owns it.
    """
    return SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
