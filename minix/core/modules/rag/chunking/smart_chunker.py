# Seven pluggable chunking strategies: smart, fixed, by_heading, by_clause, qa, sentence, llm.
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from abc import ABC, abstractmethod

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from minix.core.modules.rag.chunking.preprocessor import remove_noise, detect_sections, TextSection
from minix.core.modules.rag.config import RagConfig
from minix.core.modules.rag.llm_factory import make_llm_client


class _Strategy(ABC):
    @abstractmethod
    def chunk(self, doc: Document) -> list[Document]:
        ...

    @staticmethod
    def _tag(
        base_meta: dict,
        chunks: list[tuple[str, dict]],
        method: str,
    ) -> list[Document]:
        total = len(chunks)
        docs = []
        for i, (content, smeta) in enumerate(chunks):
            docs.append(Document(
                page_content=content,
                metadata={
                    **base_meta,
                    "chunk_index": i,
                    "total_chunks": total,
                    "section_type": smeta.get("section_type", "paragraph"),
                    "parent_heading": smeta.get("parent_heading", ""),
                    "chunk_method": method,
                },
            ))
        return docs


_ATOMIC_SECTION_TYPES = {"table", "code"}


class _SmartStrategy(_Strategy):
    """Section-aware chunker modelled on RAGflow's "naive/general" template.

    Pipeline:
      remove_noise → detect_sections → _group (respects headings, keeps tables
      and code blocks atomic) → _merge_tiny (heading-aware) → _split_big (also
      skips atomic sections) → _apply_overlap (carries trailing chars from the
      previous chunk into the next, mirroring RAGflow's token-overlap behavior)
      → _enrich_with_heading_trail (prepends parent heading to content so both
      BM25 and embeddings see the section context).
    """

    def __init__(self, chunk_size: int, chunk_overlap: int, min_chunk_size: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self._fallback = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )

    def chunk(self, doc: Document) -> list[Document]:
        base_meta = doc.metadata.copy()
        cleaned = remove_noise(doc.page_content)
        sections = detect_sections(cleaned)
        if not sections:
            # Preserve smart-method metadata even on the fallback path so
            # downstream code doesn't see a mix of tagged/untagged chunks.
            sub = self._fallback.split_documents([Document(page_content=cleaned)])
            pseudo = [
                (c.page_content, {"section_type": "paragraph", "parent_heading": ""})
                for c in sub
            ]
            overlapped = self._apply_overlap(pseudo)
            return self._tag(base_meta, overlapped, "smart")
        raw = self._group(sections)
        merged = self._merge_tiny(raw)
        final = self._split_big(merged)
        overlapped = self._apply_overlap(final)
        enriched = self._enrich_with_heading_trail(overlapped)
        return self._tag(base_meta, enriched, "smart")

    def _group(self, sections: list[TextSection]) -> list[tuple[str, dict]]:
        """Group sections into near-`chunk_size` buffers, respecting boundaries.

        Rules:
          * Every heading flushes the buffer and opens a new section.
          * Tables and code blocks are emitted as their own chunks (atomic),
            regardless of size — never co-buffered with surrounding prose.
            This matches RAGflow's invariant for these layout types.
          * Other section types accumulate until the buffer would overflow
            `chunk_size`, at which point the buffer is flushed.
        """
        grouped: list[tuple[str, dict]] = []
        buffer = ""
        buffer_meta = {"section_type": "paragraph", "parent_heading": ""}
        current_heading = ""

        def _flush():
            nonlocal buffer, buffer_meta
            if buffer.strip():
                grouped.append((buffer.strip(), buffer_meta.copy()))
            buffer = ""
            buffer_meta = {"section_type": "paragraph", "parent_heading": current_heading}

        for s in sections:
            if s.section_type == "heading":
                _flush()
                current_heading = s.content
                buffer = s.content + "\n\n"
                buffer_meta = {"section_type": "heading", "parent_heading": s.content}
                continue

            if s.section_type in _ATOMIC_SECTION_TYPES:
                # Tables and code blocks: flush current buffer, emit atomically,
                # then reset so the next prose starts fresh.
                _flush()
                grouped.append((
                    s.content.strip(),
                    {"section_type": s.section_type,
                     "parent_heading": s.parent_heading or current_heading},
                ))
                continue

            candidate = buffer + s.content + "\n\n"
            if len(candidate) <= self.chunk_size:
                buffer = candidate
                if s.section_type != "paragraph":
                    buffer_meta["section_type"] = s.section_type
                if s.parent_heading:
                    buffer_meta["parent_heading"] = s.parent_heading
                elif current_heading and not buffer_meta.get("parent_heading"):
                    buffer_meta["parent_heading"] = current_heading
            else:
                _flush()
                buffer = s.content + "\n\n"
                buffer_meta = {
                    "section_type": s.section_type,
                    "parent_heading": s.parent_heading or current_heading,
                }

        _flush()
        return grouped

    def _merge_tiny(self, chunks: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        """Carry sub-`min_chunk_size` buffers into the next chunk.

        Heading-aware: atomic sections (table/code) are never merged into, and
        we prefer to merge the carry into a chunk that shares the same parent
        heading when possible (falling back to the next chunk if not).
        """
        merged: list[tuple[str, dict]] = []
        carry = ""
        c_meta: dict = {}
        for content, meta in chunks:
            # Never fold prose into an atomic table/code chunk.
            if meta.get("section_type") in _ATOMIC_SECTION_TYPES:
                if carry:
                    # Try to fold carry backwards into the previous chunk if it
                    # shares the same parent heading.
                    if merged and merged[-1][1].get("parent_heading") == c_meta.get("parent_heading") \
                            and merged[-1][1].get("section_type") not in _ATOMIC_SECTION_TYPES:
                        lc, lm = merged[-1]
                        merged[-1] = ((lc + "\n\n" + carry).strip(), lm)
                    else:
                        merged.append((carry, c_meta))
                    carry = ""
                    c_meta = {}
                merged.append((content, meta))
                continue

            combined = (carry + "\n\n" + content).strip() if carry else content
            if len(combined) < self.min_chunk_size:
                carry = combined
                c_meta = c_meta or meta
            else:
                merged.append((combined, c_meta or meta))
                carry = ""
                c_meta = {}
        if carry:
            if merged and merged[-1][1].get("section_type") not in _ATOMIC_SECTION_TYPES:
                lc, lm = merged[-1]
                merged[-1] = (lc + "\n\n" + carry, lm)
            else:
                merged.append((carry, c_meta))
        return merged

    def _split_big(self, chunks: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        """Split oversized chunks — except tables and code, which stay atomic.

        Sub-chunks born from one oversized parent are tagged with a shared
        `_split_origin` marker so `_apply_overlap` can skip them — the splitter
        has already applied its own overlap between those sub-chunks and we
        must not double up.
        """
        result: list[tuple[str, dict]] = []
        for idx, (content, meta) in enumerate(chunks):
            if len(content) <= self.chunk_size:
                result.append((content, meta))
                continue
            if meta.get("section_type") in _ATOMIC_SECTION_TYPES:
                # Keep atomic — accept the oversize. RAGflow does the same.
                result.append((content, meta))
                continue
            sub = self._fallback.split_documents([Document(page_content=content)])
            origin_key = f"split_{idx}"
            for sc in sub:
                sub_meta = {**meta, "_split_origin": origin_key}
                result.append((sc.page_content, sub_meta))
        return result

    def _apply_overlap(self, chunks: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        """Prepend the tail of chunk K onto chunk K+1 so adjacent chunks overlap.

        Zero-cost no-op when `chunk_overlap <= 0`. Overlap is skipped when the
        donor or receiver is an atomic section (table/code) — matching RAGflow,
        which does not bleed prose into tables or vice versa.
        """
        if self.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks
        out: list[tuple[str, dict]] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_content, prev_meta = chunks[i - 1]
            curr_content, curr_meta = chunks[i]
            # Sibling sub-chunks produced by `_split_big` already overlap via
            # the recursive splitter — don't double up.
            shared_origin = prev_meta.get("_split_origin")
            if shared_origin and shared_origin == curr_meta.get("_split_origin"):
                out.append((curr_content, curr_meta))
                continue
            prev_is_atomic = prev_meta.get("section_type") in _ATOMIC_SECTION_TYPES
            curr_is_atomic = curr_meta.get("section_type") in _ATOMIC_SECTION_TYPES
            if prev_is_atomic or curr_is_atomic:
                out.append((curr_content, curr_meta))
                continue
            tail = prev_content[-self.chunk_overlap:] \
                if len(prev_content) > self.chunk_overlap else prev_content
            # Start tail at the next word boundary when one is available in
            # the first half — avoids mid-word cuts like "…tern economy".
            if len(tail) > 8:
                cut = tail.find(" ")
                if 0 < cut < len(tail) // 2:
                    tail = tail[cut + 1:]
            combined = (tail.strip() + "\n\n" + curr_content).strip()
            out.append((combined, curr_meta))
        return out

    def _enrich_with_heading_trail(
        self, chunks: list[tuple[str, dict]]
    ) -> list[tuple[str, dict]]:
        """Prepend parent heading to chunk content when it isn't already there.

        RAGflow does this so both BM25 and embeddings see the section context;
        chunks deep in a document become self-identifying ("Eligibility" under
        "Article 3" is clearly different from "Eligibility" under "Article 7").
        """
        out: list[tuple[str, dict]] = []
        for content, meta in chunks:
            heading = (meta.get("parent_heading") or "").strip()
            if meta.get("section_type") == "heading":
                out.append((content, meta))
                continue
            if heading and heading not in content[: len(heading) + 4]:
                enriched = f"{heading}\n\n{content}"
                out.append((enriched, meta))
            else:
                out.append((content, meta))
        return out


class _FixedStrategy(_Strategy):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )

    def chunk(self, doc: Document) -> list[Document]:
        base_meta = doc.metadata.copy()
        raw = self._splitter.split_documents([doc])
        return self._tag(
            base_meta,
            [(c.page_content, {"section_type": "paragraph", "parent_heading": ""}) for c in raw],
            "fixed",
        )


class _ByHeadingStrategy(_Strategy):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self._fallback = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )

    def chunk(self, doc: Document) -> list[Document]:
        base_meta = doc.metadata.copy()
        cleaned = remove_noise(doc.page_content)
        sections = detect_sections(cleaned)
        raw: list[tuple[str, dict]] = []
        buf = ""
        heading = ""
        for s in sections:
            if s.section_type == "heading":
                if buf.strip():
                    raw.append((buf.strip(), {"section_type": "heading", "parent_heading": heading}))
                buf = s.content + "\n\n"
                heading = s.content
            else:
                buf += s.content + "\n\n"
        if buf.strip():
            raw.append((buf.strip(), {"section_type": "heading", "parent_heading": heading}))
        final: list[tuple[str, dict]] = []
        for content, meta in raw:
            if len(content) > self.chunk_size:
                for sc in self._fallback.split_documents([Document(page_content=content)]):
                    final.append((sc.page_content, meta))
            else:
                final.append((content, meta))
        return self._tag(base_meta, final, "by_heading")


_CLAUSE_PATTERN = re.compile(
    r"(?:^|\n)(?=(?:article|clause|section|paragraph|schedule|annexure|exhibit)\s+[\d.]+[.:]?\s)",
    re.IGNORECASE,
)


class _ByClauseStrategy(_Strategy):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self._fallback = _SmartStrategy(chunk_size, chunk_overlap, 100)
        self._oversized = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def chunk(self, doc: Document) -> list[Document]:
        base_meta = doc.metadata.copy()
        text = remove_noise(doc.page_content)
        parts = _CLAUSE_PATTERN.split(text)
        if len(parts) <= 1:
            return self._fallback.chunk(doc)
        raw: list[tuple[str, dict]] = []
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            heading = part.splitlines()[0][:80] if part else f"Clause {i}"
            raw.append((part, {"section_type": "clause", "parent_heading": heading}))
        final: list[tuple[str, dict]] = []
        for content, meta in raw:
            if len(content) > self.chunk_size:
                for sc in self._oversized.split_documents([Document(page_content=content)]):
                    final.append((sc.page_content, meta))
            else:
                final.append((content, meta))
        return self._tag(base_meta, final, "by_clause")


_QUESTION_LINE = re.compile(r"^(?:Q:|Question\s*\d*[:.]\s*|#{1,3}\s*.+\?)", re.IGNORECASE)


class _QAStrategy(_Strategy):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self._fallback = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def chunk(self, doc: Document) -> list[Document]:
        base_meta = doc.metadata.copy()
        text = remove_noise(doc.page_content)
        lines = text.splitlines()
        raw: list[tuple[str, dict]] = []
        buf = ""
        heading = ""
        found_qa = False
        for line in lines:
            if _QUESTION_LINE.match(line.strip()):
                found_qa = True
                if buf.strip():
                    raw.append((buf.strip(), {"section_type": "qa_pair", "parent_heading": heading}))
                buf = line + "\n"
                heading = line.strip()
            else:
                buf += line + "\n"
        if buf.strip():
            raw.append((buf.strip(), {"section_type": "qa_pair", "parent_heading": heading}))
        if not found_qa:
            chunks = self._fallback.split_documents([Document(page_content=text)])
            return self._tag(
                base_meta,
                [(c.page_content, {"section_type": "paragraph", "parent_heading": ""}) for c in chunks],
                "qa",
            )
        return self._tag(base_meta, raw, "qa")


_SENT_END = re.compile(r"(?<=[.!?])\s+")


class _SentenceStrategy(_Strategy):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, doc: Document) -> list[Document]:
        base_meta = doc.metadata.copy()
        text = remove_noise(doc.page_content)
        sentences = _SENT_END.split(text)
        raw: list[tuple[str, dict]] = []
        buf = ""
        for sent in sentences:
            candidate = (buf + " " + sent).strip() if buf else sent.strip()
            if len(candidate) <= self.chunk_size:
                buf = candidate
            else:
                if buf:
                    raw.append((buf, {"section_type": "paragraph", "parent_heading": ""}))
                buf = sent.strip()
        if buf:
            raw.append((buf, {"section_type": "paragraph", "parent_heading": ""}))
        return self._tag(base_meta, raw, "sentence")


_LLM_SYSTEM = """\
You are a document chunking assistant. Your job is to decide where to split a
list of structured text segments into coherent, self-contained chunks based on
the user's instruction.

You will receive:
1. A numbered list of segments (index 0, 1, 2, …), including section type and
   parent heading.
2. A chunking instruction from the user.

Your task is to identify which segment indices START a new chunk.
Index 0 always starts the first chunk (include it).

Universal rules:
- Never leave a heading as the final content of a chunk. A heading starts the
  chunk containing the content that follows it.
- Keep a rule with its exception, proviso, carve-out, deadline, remedy, or
  condition.
- Keep examples with the rule they explain.
- Preserve parent section context when a chunk begins below a heading.
- Prefer complete legal/document units over exact size targets.
- Do not rewrite, summarize, or omit source text.

Return ONLY JSON matching this shape:
{"start_indices": [0, 3, 7, 12]}

No explanation. No markdown fences. Pure JSON only."""

_LLM_USER_TEMPLATE = """\
Chunking instruction:
{instruction}

Segments:
{segments_text}

Return the start indices as JSON."""

_LLM_REPAIR_USER_TEMPLATE = """\
Chunking instruction:
{instruction}

The current boundaries produced suspicious chunks:
{warnings}

Current start indices:
{boundaries}

Segments:
{segments_text}

Return corrected start indices as JSON. Do not rewrite any text."""


class _ChunkBoundaryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_indices: list[int] = Field(
        description="Segment indices that start chunks. Must include 0."
    )


@dataclass
class _ChunkSegment:
    content: str
    section_type: str
    parent_heading: str = ""

    @property
    def is_heading(self) -> bool:
        return self.section_type == "heading"


class _LLMStrategy(_Strategy):
    MAX_SEGMENTS_PER_WINDOW = 40

    def __init__(self, chunk_size: int, chunk_overlap: int, instruction: str,
                 min_chunk_size: int = 100, collection: str = "",
                 cost_tracker=None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.instruction = instruction
        self.min_chunk_size = min_chunk_size
        self.collection = collection
        self._cost_tracker = cost_tracker
        self._client = make_llm_client()
        self._model = RagConfig.DOCUMENT_PROCESSOR_MODEL
        self.warnings: list[str] = []
        self.fallback_used = False
        self.effective_method = "llm"
        self._fallback = _SmartStrategy(chunk_size, chunk_overlap, min_chunk_size)
        self._oversized = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def chunk(self, doc: Document) -> list[Document]:
        base_meta = doc.metadata.copy()
        text = remove_noise(doc.page_content)
        segments = self._structured_segments(text)
        if not segments:
            return self._fallback_docs(doc, "no_segments")
        try:
            boundaries = self._detect_boundaries(segments)
            boundaries, repair_warnings = self._repair_boundaries(segments, boundaries)
            self.warnings.extend(repair_warnings)
        except Exception as exc:
            return self._fallback_docs(doc, f"llm_boundary_detection_failed:{type(exc).__name__}")

        groups = self._assemble_groups(segments, boundaries)
        suspicious = self._find_chunk_warnings(groups)
        if suspicious and RagConfig.LLM_CHUNK_REPAIR_ENABLED:
            try:
                repaired = self._call_repair_llm(segments, boundaries, suspicious)
                repaired, repair_warnings = self._repair_boundaries(segments, repaired)
                repaired_groups = self._assemble_groups(segments, repaired)
                repaired_suspicious = self._find_chunk_warnings(repaired_groups)
                if len(repaired_suspicious) <= len(suspicious):
                    boundaries = repaired
                    groups = repaired_groups
                    suspicious = repaired_suspicious
                    self.warnings.append("llm_repair_applied")
                else:
                    self.warnings.append("llm_repair_rejected")
                self.warnings.extend(repair_warnings)
            except Exception as exc:
                self.warnings.append(f"llm_repair_failed:{type(exc).__name__}")
        elif suspicious:
            self.warnings.append("llm_repair_skipped_disabled")
        self.warnings.extend(suspicious)

        assembled = self._split_oversized_groups(groups)
        assembled = self._enrich_with_heading_trail(assembled)
        final: list[tuple[str, dict]] = []
        for content, meta in assembled:
            final.append((content, meta))
        return self._tag(base_meta, final, "llm")

    def _fallback_docs(self, doc: Document, reason: str) -> list[Document]:
        self.fallback_used = True
        self.effective_method = "smart"
        self.warnings.append(reason)
        return self._fallback.chunk(doc)

    def _structured_segments(self, text: str) -> list[_ChunkSegment]:
        sections = detect_sections(text)
        if not sections:
            raw = [s.strip() for s in re.split(r"\n{2,}", text) if s.strip()]
            return [_ChunkSegment(s, "paragraph", "") for s in raw]
        return [
            _ChunkSegment(
                content=s.content.strip(),
                section_type=s.section_type or "paragraph",
                parent_heading=s.parent_heading or "",
            )
            for s in sections
            if s.content.strip()
        ]

    def _detect_boundaries(self, segments: list[_ChunkSegment]) -> list[int]:
        W = self.MAX_SEGMENTS_PER_WINDOW
        overlap = max(0, min(RagConfig.LLM_CHUNK_WINDOW_OVERLAP, W - 1))
        step = max(1, W - overlap)
        all_boundaries: list[int] = []
        for window_start in range(0, len(segments), step):
            window = segments[window_start: window_start + W]
            local_boundaries = self._call_llm(window)
            global_boundaries = [
                window_start + i
                for i in local_boundaries
                if window_start == 0 or window_start + i > window_start
            ]
            all_boundaries.extend(global_boundaries)
            if window_start + W >= len(segments):
                break
        return self._normalize_boundaries(all_boundaries, len(segments))

    def _normalize_boundaries(self, boundaries: list[int], segment_count: int) -> list[int]:
        seen = set()
        deduped = []
        for b in boundaries:
            if 0 <= int(b) < segment_count and b not in seen:
                seen.add(b)
                deduped.append(int(b))
        deduped.sort()
        if not deduped or deduped[0] != 0:
            deduped.insert(0, 0)
        return deduped

    def _segments_for_prompt(self, segments: list[_ChunkSegment]) -> str:
        limit = max(80, RagConfig.LLM_CHUNK_SEGMENT_PREVIEW_CHARS)
        rows = []
        for i, seg in enumerate(segments):
            preview = seg.content[:limit]
            rows.append(
                f"{i}: type={seg.section_type}; parent_heading={seg.parent_heading!r}\n"
                f"{preview}"
            )
        return "\n\n---\n\n".join(rows)

    def _call_llm(self, segments: list[_ChunkSegment]) -> list[int]:
        user_content = _LLM_USER_TEMPLATE.format(
            instruction=self.instruction,
            segments_text=self._segments_for_prompt(segments),
        )
        return self._call_boundary_model(
            user_content,
            len(segments),
            operation="LLM Chunking",
            description=f"chunk window ({len(segments)} segments)",
        )

    def _call_repair_llm(
        self,
        segments: list[_ChunkSegment],
        boundaries: list[int],
        warnings: list[str],
    ) -> list[int]:
        user_content = _LLM_REPAIR_USER_TEMPLATE.format(
            instruction=self.instruction,
            warnings="\n".join(f"- {w}" for w in warnings[:12]),
            boundaries=json.dumps(boundaries),
            segments_text=self._segments_for_prompt(segments),
        )
        return self._call_boundary_model(
            user_content,
            len(segments),
            operation="LLM Chunk Repair",
            description=f"repair chunk boundaries ({len(segments)} segments)",
        )

    def _call_boundary_model(
        self,
        user_content: str,
        segment_count: int,
        *,
        operation: str,
        description: str,
    ) -> list[int]:
        raw = ""
        response_kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        }
        try:
            response = self._client.chat.completions.create(
                **response_kwargs,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "chunk_boundary_plan",
                        "schema": _ChunkBoundaryPlan.model_json_schema(),
                        "strict": True,
                    },
                },
            )
            raw = response.choices[0].message.content.strip()
        except Exception:
            response = self._client.chat.completions.create(**response_kwargs)
            raw = response.choices[0].message.content.strip()
        try:
            parsed = self._parse_boundary_response(raw, segment_count)
        except Exception:
            response = self._client.chat.completions.create(**response_kwargs)
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_boundary_response(raw, segment_count)
        if self._cost_tracker:
            try:
                self._cost_tracker.record(
                    operation=operation,
                    collection=self.collection,
                    description=description,
                    input_text=_LLM_SYSTEM + user_content,
                    output_text=raw,
                    model=self._model,
                )
            except Exception:
                pass
        return parsed

    def _parse_boundary_response(self, raw: str, segment_count: int) -> list[int]:
        fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        if fence:
            raw = fence.group(1)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            parsed = {"start_indices": parsed}
        try:
            plan = _ChunkBoundaryPlan.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError(f"LLM returned invalid boundaries: {parsed!r}") from exc
        return self._normalize_boundaries(plan.start_indices, segment_count)

    def _repair_boundaries(
        self,
        segments: list[_ChunkSegment],
        boundaries: list[int],
    ) -> tuple[list[int], list[str]]:
        warnings: list[str] = []
        repaired = self._normalize_boundaries(boundaries, len(segments))
        changed = True
        while changed:
            changed = False
            for k, start in enumerate(list(repaired)):
                end = repaired[k + 1] if k + 1 < len(repaired) else len(segments)
                group = segments[start:end]
                if not group:
                    continue
                if len(group) == 1 and group[0].is_heading and end < len(segments):
                    if end in repaired:
                        repaired.remove(end)
                        warnings.append(f"merged_orphan_heading_at_segment_{start}")
                        changed = True
                        break
                if len(group) > 1 and group[-1].is_heading and end < len(segments):
                    if end - 1 not in repaired:
                        repaired.append(end - 1)
                        repaired = self._normalize_boundaries(repaired, len(segments))
                        warnings.append(f"moved_trailing_heading_at_segment_{end - 1}")
                        changed = True
                        break
                if start > 0 and self._starts_like_exception(group[0].content):
                    repaired.remove(start)
                    warnings.append(f"merged_exception_chunk_at_segment_{start}")
                    changed = True
                    break
                size = len("\n\n".join(s.content for s in group))
                if (
                    start > 0
                    and size < self.min_chunk_size
                    and not self._is_complete_definition(group)
                    and not any(s.section_type in _ATOMIC_SECTION_TYPES for s in group)
                ):
                    repaired.remove(start)
                    warnings.append(f"merged_tiny_incomplete_chunk_at_segment_{start}")
                    changed = True
                    break
        return self._normalize_boundaries(repaired, len(segments)), warnings

    @staticmethod
    def _starts_like_exception(text: str) -> bool:
        t = text.strip().lower()
        return t.startswith((
            "except ",
            "unless ",
            "provided that ",
            "provided, however",
            "subject to ",
            "notwithstanding ",
            "by contrast",
            "a disclosure required",
            "disclosure required",
            "however,",
        ))

    @staticmethod
    def _is_complete_definition(group: list[_ChunkSegment]) -> bool:
        if len(group) != 1:
            return False
        text = group[0].content.strip()
        return bool(re.match(r"^[\"“][^\"”]+[\"”]\s+means\b", text, re.IGNORECASE))

    def _assemble_groups(
        self,
        segments: list[_ChunkSegment],
        boundaries: list[int],
    ) -> list[tuple[list[_ChunkSegment], dict]]:
        chunks: list[tuple[list[_ChunkSegment], dict]] = []
        for k, start in enumerate(boundaries):
            end = boundaries[k + 1] if k + 1 < len(boundaries) else len(segments)
            group = segments[start:end]
            if group:
                chunks.append((group, self._group_meta(group)))
        return chunks

    def _group_meta(self, group: list[_ChunkSegment]) -> dict:
        parent = ""
        if group and group[0].is_heading:
            parent = group[0].content
        else:
            for seg in group:
                if seg.parent_heading:
                    parent = seg.parent_heading
                    break
        return {"section_type": "llm_chunk", "parent_heading": parent}

    def _find_chunk_warnings(
        self,
        groups: list[tuple[list[_ChunkSegment], dict]],
    ) -> list[str]:
        warnings: list[str] = []
        for i, (group, meta) in enumerate(groups):
            if not group:
                continue
            if group[-1].is_heading and i + 1 < len(groups):
                warnings.append(f"chunk_{i}_ends_with_heading")
            if group[0].is_heading and len(group) == 1 and i + 1 < len(groups):
                warnings.append(f"chunk_{i}_heading_without_body")
            if i > 0 and self._starts_like_exception(group[0].content):
                warnings.append(f"chunk_{i}_starts_with_exception")
            content = "\n\n".join(seg.content for seg in group)
            if (
                len(content) < self.min_chunk_size
                and not self._is_complete_definition(group)
                and not any(seg.section_type in _ATOMIC_SECTION_TYPES for seg in group)
            ):
                warnings.append(f"chunk_{i}_tiny_incomplete")
        return warnings

    def _split_oversized_groups(
        self,
        groups: list[tuple[list[_ChunkSegment], dict]],
    ) -> list[tuple[str, dict]]:
        final: list[tuple[str, dict]] = []
        for idx, (group, meta) in enumerate(groups):
            content = self._join_group(group)
            if len(content) <= self.chunk_size or len(group) == 1:
                final.extend(self._split_single_if_needed(content, meta, idx))
                continue
            current: list[_ChunkSegment] = []
            for seg in group:
                candidate = self._join_group([*current, seg])
                if current and len(candidate) > self.chunk_size:
                    if len(current) == 1 and current[0].is_heading:
                        current.append(seg)
                        continue
                    final.append((self._join_group(current), self._group_meta(current)))
                    current = [seg]
                else:
                    current.append(seg)
            if current:
                final.extend(
                    self._split_single_if_needed(
                        self._join_group(current),
                        self._group_meta(current),
                        idx,
                    )
                )
        return final

    def _split_single_if_needed(
        self,
        content: str,
        meta: dict,
        idx: int,
    ) -> list[tuple[str, dict]]:
        if len(content) <= self.chunk_size or meta.get("section_type") in _ATOMIC_SECTION_TYPES:
            return [(content, meta)]
        origin_key = f"llm_split_{idx}"
        return [
            (sc.page_content, {**meta, "_split_origin": origin_key})
            for sc in self._oversized.split_documents([Document(page_content=content)])
        ]

    @staticmethod
    def _join_group(group: list[_ChunkSegment]) -> str:
        return "\n\n".join(seg.content for seg in group).strip()

    def _enrich_with_heading_trail(
        self,
        chunks: list[tuple[str, dict]],
    ) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for content, meta in chunks:
            heading = (meta.get("parent_heading") or "").strip()
            if heading and heading not in content[: len(heading) + 4]:
                out.append((f"{heading}\n\n{content}", meta))
            else:
                out.append((content, meta))
        return out


_STRATEGIES: dict[str, type[_Strategy]] = {
    "smart": _SmartStrategy,
    "fixed": _FixedStrategy,
    "by_heading": _ByHeadingStrategy,
    "by_clause": _ByClauseStrategy,
    "qa": _QAStrategy,
    "sentence": _SentenceStrategy,
    "llm": _LLMStrategy,
}

# API-owned UI metadata for the selectable chunking strategies. Keyed by the
# same identifiers as _STRATEGIES so consumers never duplicate the enum. The
# controller exposes this verbatim via GET /rag/chunking/strategies; the React
# UI renders option_label/description from it instead of hard-coding labels.
STRATEGY_METADATA: list[dict] = [
    {
        "value": "smart",
        "label": "Smart (section-aware)",
        "option_label": "Smart",
        "description": "Section-aware splitting that respects document structure and headings. Recommended default.",
        "requires_instruction": False,
    },
    {
        "value": "fixed",
        "label": "Fixed-size",
        "option_label": "Fixed",
        "description": "Splits text into fixed-size chunks with overlap, ignoring document structure.",
        "requires_instruction": False,
    },
    {
        "value": "by_heading",
        "label": "By heading",
        "option_label": "By heading",
        "description": "Splits at document headings, keeping each section together.",
        "requires_instruction": False,
    },
    {
        "value": "by_clause",
        "label": "By clause",
        "option_label": "By clause",
        "description": "Splits along numbered/legal clauses; falls back to smart chunking when no clauses are found.",
        "requires_instruction": False,
    },
    {
        "value": "qa",
        "label": "Q&A pairs",
        "option_label": "Q&A",
        "description": "Groups question/answer pairs into chunks, suited to FAQ-style documents.",
        "requires_instruction": False,
    },
    {
        "value": "sentence",
        "label": "By sentence",
        "option_label": "Sentence",
        "description": "Splits on sentence boundaries, packing sentences up to the chunk size.",
        "requires_instruction": False,
    },
    {
        "value": "llm",
        "label": "LLM-guided",
        "option_label": "LLM",
        "description": "Uses an LLM to segment text following your natural-language instruction. Requires an instruction.",
        "requires_instruction": True,
    },
]

# Guard against drift between the executable strategy registry and its metadata.
assert {m["value"] for m in STRATEGY_METADATA} == set(_STRATEGIES), (
    "STRATEGY_METADATA keys must match _STRATEGIES"
)


class SmartChunker:
    def __init__(self, cost_tracker=None):
        self._cost_tracker = cost_tracker

    @staticmethod
    def _stamp_runtime(
        docs: list[Document],
        *,
        requested: str,
        effective: str,
        fallback: bool,
        warnings: list[str],
    ) -> list[Document]:
        for doc in docs:
            doc.metadata["chunking_strategy_requested"] = requested
            doc.metadata["chunking_strategy_effective"] = effective
            doc.metadata["llm_chunking_fallback"] = fallback
            doc.metadata["llm_chunking_warnings"] = list(dict.fromkeys(warnings))
        return docs

    def chunk(self, doc: Document, config: dict | None = None) -> list[Document]:
        if not config:
            config = {}
        strategy_name = config.get("strategy", "smart").lower()
        requested_strategy = strategy_name
        chunk_size = int(config.get("chunk_size", RagConfig.CHUNK_SIZE))
        chunk_overlap = int(config.get("chunk_overlap", RagConfig.CHUNK_OVERLAP))
        min_chunk = int(config.get("min_chunk_size", 100))
        strategy_cls = _STRATEGIES.get(strategy_name)
        if strategy_cls is None:
            strategy_cls = _SmartStrategy
            strategy_name = "smart"
        if strategy_cls is _LLMStrategy:
            instruction = config.get("instruction") or ""
            collection = config.get("_collection_name", "")
            if not instruction:
                strategy = _SmartStrategy(chunk_size, chunk_overlap, min_chunk)
                docs = strategy.chunk(doc)
                return self._stamp_runtime(
                    docs,
                    requested="llm",
                    effective="smart",
                    fallback=True,
                    warnings=["missing_llm_instruction"],
                )
            else:
                strategy = _LLMStrategy(chunk_size, chunk_overlap, instruction,
                                        min_chunk, collection, self._cost_tracker)
                docs = strategy.chunk(doc)
                return self._stamp_runtime(
                    docs,
                    requested="llm",
                    effective=strategy.effective_method,
                    fallback=strategy.fallback_used,
                    warnings=strategy.warnings,
                )
        elif strategy_cls is _SmartStrategy:
            strategy = _SmartStrategy(chunk_size, chunk_overlap, min_chunk)
        else:
            strategy = strategy_cls(chunk_size, chunk_overlap)
        docs = strategy.chunk(doc)
        return self._stamp_runtime(
            docs,
            requested=strategy_name,
            effective=strategy_name,
            fallback=requested_strategy != strategy_name,
            warnings=[],
        )
