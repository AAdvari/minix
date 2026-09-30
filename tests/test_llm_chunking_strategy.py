from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from minix.core.modules.rag.chunking.smart_chunker import (
    _ChunkSegment,
    _LLMStrategy,
    _SmartStrategy,
)
from minix.core.modules.rag.config import RagConfig


LEGAL_ADDENDUM_EXCERPT = """\
2. Definitions

“Customer Data” means documents, text, images, metadata, prompts, retrieval results, annotations, and other content submitted by or on behalf of the Customer to the Processor.

“Confidential Information” means non-public business, technical, financial, operational, or legal information disclosed by one party to the other, whether orally, visually, electronically, or in writing. Confidential Information does not include information that the receiving party can prove was already known without restriction, independently developed without use of the disclosing party’s information, lawfully received from a third party, or publicly available through no fault of the receiving party.

“Security Incident” means unauthorized access to, acquisition of, disclosure of, alteration of, or loss of Customer Data. Failed login attempts, port scans, spam, denial-of-service traffic, or unsuccessful attacks that do not compromise Customer Data are not Security Incidents unless they materially degrade the confidentiality, integrity, or availability of Customer Data.

“Subprocessor” means a third party engaged by the Processor to process Customer Data for the purpose of delivering the services.

3. Processing Instructions

The Processor may process Customer Data only to provide, secure, maintain, support, and improve the contracted services, and only in accordance with the Customer’s documented instructions. The Customer’s documented instructions include configuration settings, API requests, uploaded files, retrieval queries, administrative actions, and written instructions from authorized Customer personnel.

The Processor must not sell Customer Data, use Customer Data to train a general-purpose model unless the Customer has expressly opted in, or disclose Customer Data to any third party except as permitted by this Addendum. The Processor may process Customer Data to detect abuse, prevent fraud, maintain service reliability, and comply with applicable law, provided that such processing is limited to what is reasonably necessary for those purposes.

4. Confidentiality Obligations

Each party must protect the other party’s Confidential Information using at least reasonable care and no less than the care it uses to protect its own similar information. The receiving party may use Confidential Information only to perform obligations or exercise rights under the agreement.

The receiving party may disclose Confidential Information to its employees, contractors, professional advisers, auditors, and affiliates only if they have a need to know and are bound by confidentiality obligations at least as protective as those in this Addendum. The receiving party remains responsible for any breach of confidentiality by those recipients.

A disclosure required by law, subpoena, court order, or government authority is not a breach if the receiving party gives prompt notice to the disclosing party, unless notice is legally prohibited, and cooperates with reasonable efforts to limit the disclosure.

5. Security Measures

The Processor must maintain administrative, technical, and physical safeguards designed to protect Customer Data against accidental or unlawful destruction, loss, alteration, unauthorized disclosure, or unauthorized access. These safeguards must include access controls, encryption in transit, logging of administrative access, vulnerability management, backup controls, and employee security training.

Customer Data must be logically separated from other customers’ data. Production access to Customer Data must be limited to personnel with a legitimate operational need. The Processor must review privileged access at least quarterly and remove access when it is no longer required.

The Customer is responsible for configuring user permissions, protecting account credentials, rotating API keys, and ensuring that Customer users submit Customer Data lawfully.
"""


def _strategy(chunk_size: int = 3000, min_chunk_size: int = 100) -> _LLMStrategy:
    strategy = object.__new__(_LLMStrategy)
    strategy.chunk_size = chunk_size
    strategy.chunk_overlap = 0
    strategy.instruction = "Chunk legal documents by complete legal meaning."
    strategy.min_chunk_size = min_chunk_size
    strategy.collection = "legal"
    strategy._cost_tracker = None
    strategy._client = None
    strategy._model = "test-model"
    strategy.warnings = []
    strategy.fallback_used = False
    strategy.effective_method = "llm"
    strategy._fallback = _SmartStrategy(chunk_size, 0, min_chunk_size)
    strategy._oversized = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=0,
    )
    return strategy


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class _FakeTracker:
    def __init__(self):
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)


def test_legal_boundaries_are_repaired_and_context_is_preserved(monkeypatch):
    monkeypatch.setattr(RagConfig, "LLM_CHUNK_REPAIR_ENABLED", False)
    strategy = _strategy()

    def fake_detect(segments):
        first_lines = [s.content.splitlines()[0] for s in segments]
        assert first_lines[5] == "3. Processing Instructions"
        assert first_lines[8] == "4. Confidentiality Obligations"
        assert first_lines[12] == "5. Security Measures"
        # Deliberately bad: segment 5 is a trailing heading on the previous
        # definitions chunk, segment 11 is an exception-only confidentiality
        # chunk, and segment 15 is split away from Security Measures.
        return [0, 2, 6, 8, 10, 11, 12, 13, 15]

    strategy._detect_boundaries = fake_detect
    strategy._call_repair_llm = lambda *args, **kwargs: pytest.fail(
        "repair should be disabled"
    )

    docs = strategy.chunk(Document(page_content=LEGAL_ADDENDUM_EXCERPT, metadata={}))
    texts = [d.page_content for d in docs]

    assert not any(t.strip().endswith("3. Processing Instructions") for t in texts)
    assert any(
        "3. Processing Instructions" in t
        and "The Processor must not sell Customer Data" in t
        for t in texts
    )
    assert any(
        "4. Confidentiality Obligations" in t
        and "A disclosure required by law" in t
        for t in texts
    )
    assert any(
        t.startswith("5. Security Measures")
        and "The Customer is responsible for configuring user permissions" in t
        for t in texts
    )
    assert not strategy.fallback_used
    assert "llm_repair_skipped_disabled" not in strategy.warnings


def test_call_llm_uses_structured_output_then_json_retry():
    strategy = _strategy()

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                assert "response_format" in kwargs
                return _response("not json")
            assert "response_format" not in kwargs
            return _response('{"start_indices": [0, 2]}')

    completions = FakeCompletions()
    strategy._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = strategy._call_llm([
        _ChunkSegment("Heading", "heading"),
        _ChunkSegment("Body one", "paragraph", "Heading"),
        _ChunkSegment("Body two", "paragraph", "Heading"),
    ])

    assert result == [0, 2]
    assert len(completions.calls) == 2


def test_repair_llm_records_cost():
    strategy = _strategy()
    tracker = _FakeTracker()
    strategy._cost_tracker = tracker
    strategy._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: _response('{"start_indices": [0]}')
            )
        )
    )

    result = strategy._call_repair_llm(
        [_ChunkSegment("A disclosure required by law is not a breach.", "paragraph")],
        [0],
        ["chunk_0_starts_with_exception"],
    )

    assert result == [0]
    assert tracker.records[0]["operation"] == "LLM Chunk Repair"


def test_llm_repair_is_not_called_when_disabled(monkeypatch):
    monkeypatch.setattr(RagConfig, "LLM_CHUNK_REPAIR_ENABLED", False)
    strategy = _strategy()
    strategy._detect_boundaries = lambda segments: [0]
    strategy._find_chunk_warnings = lambda groups: ["still_suspicious"]
    strategy._call_repair_llm = lambda *args, **kwargs: pytest.fail(
        "repair should not run while disabled"
    )

    docs = strategy.chunk(Document(page_content="1. Scope\n\nA short body.", metadata={}))

    assert docs
    assert "llm_repair_skipped_disabled" in strategy.warnings


def test_oversized_groups_split_on_structured_boundaries_before_recursive():
    strategy = _strategy(chunk_size=90)

    class FailingSplitter:
        def split_documents(self, docs):
            raise AssertionError("recursive fallback should not be needed")

    strategy._oversized = FailingSplitter()
    group = [
        _ChunkSegment("1. Scope", "heading"),
        _ChunkSegment("Alpha " * 8, "paragraph", "1. Scope"),
        _ChunkSegment("Beta " * 8, "paragraph", "1. Scope"),
        _ChunkSegment("Gamma " * 8, "paragraph", "1. Scope"),
    ]

    chunks = strategy._split_oversized_groups([(group, strategy._group_meta(group))])
    enriched = strategy._enrich_with_heading_trail(chunks)

    assert len(enriched) > 1
    assert all("1. Scope" in content for content, _meta in enriched)
