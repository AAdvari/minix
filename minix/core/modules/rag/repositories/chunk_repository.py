# Repository for RAG chunks: bulk insert and BM25 full-text search.
import re
from typing import List

from sqlalchemy import text

from minix.core.repository import SqlRepository
from minix.core.modules.rag.config import RagConfig
from minix.core.modules.rag.entities.chunk_entity import RagChunkEntity


_METADATA_FILTER_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

# OR-mode keyword query construction. We extract lexeme tokens and OR-join them
# so that, unlike plainto_tsquery (which ANDs every token), a long natural-
# language query still matches chunks sharing *any* salient term — ts_rank then
# orders them. We drop ≤2-char tokens and the highest-frequency stopwords so the
# generated tsquery stays small and avoids matching nearly every chunk. (Postgres'
# english dictionary inside to_tsquery also strips stopwords, but pre-filtering
# keeps the query tight.)
_OR_TOKEN = re.compile(r"[a-z0-9]+")
_OR_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "be", "by", "that", "this", "it", "as", "at", "from", "does", "do",
    "shall", "may", "any", "some", "upon", "whether", "which", "their", "its",
    "not", "no", "was", "were", "will", "would", "can", "could", "if", "than",
})


def _keyword_match(query: str) -> tuple[str, dict]:
    """Build the SQL ts_query expression + bind params for the keyword leg.

    Returns a code-controlled SQL fragment (safe to interpolate; the user text
    is always passed as a bound parameter) and the params to bind. In ``or``
    mode, falls back to ``plainto`` when the query has no usable tokens so
    behavior never silently becomes "match everything".
    """
    if RagConfig.BM25_QUERY_MODE == "or":
        tokens = [
            t for t in _OR_TOKEN.findall(query.lower())
            if len(t) > 2 and t not in _OR_STOPWORDS
        ]
        if tokens:
            return "to_tsquery('english', :tsquery)", {"tsquery": " | ".join(tokens)}
    return "plainto_tsquery('english', :query)", {"query": query}


class RagChunkRepository(SqlRepository[RagChunkEntity]):

    def add_chunks(self, document_id: int, collection_name: str,
                   chunks: list[dict]) -> None:
        with self.get_session() as session:
            # Construct via self.entity (not the imported class) so a mounted
            # entity subclass — e.g. one that adds scope stamping — takes effect
            # without editing this method.
            rows = [
                self.entity(
                    document_id=document_id,
                    collection_name=collection_name,
                    content=c["content"],
                    chunk_index=c.get("chunk_index"),
                    section_type=c.get("section_type"),
                    parent_heading=c.get("parent_heading"),
                )
                for c in chunks
            ]
            session.bulk_save_objects(rows)
            session.commit()

    def bm25_search(self, query: str, collection_name: str,
                    k: int = 10,
                    allowed_doc_uuids: set[str] | list[str] | None = None,
                    extra_filters: dict[str, int | str] | None = None) -> List[dict]:
        # Empty set means "caller may see nothing" — short-circuit. None means
        # "no access filter". Caller-supplied filters cannot widen this.
        if allowed_doc_uuids is not None and len(allowed_doc_uuids) == 0:
            return []
        access_clause = ""
        kw_expr, kw_params = _keyword_match(query)
        params: dict = {"collection": collection_name, "k": k, **kw_params}
        if allowed_doc_uuids is not None:
            access_clause = "AND d.doc_uuid::text = ANY(:allowed_uuids)"
            params["allowed_uuids"] = [str(u) for u in allowed_doc_uuids]
        # Generic scope filters — the framework's scope injection point. Each
        # column is whitelisted against the chunk entity's own columns and
        # rendered as `AND c.<col> = :<col>` with a bound parameter.
        if extra_filters:
            for col, val in extra_filters.items():
                if col not in self.entity.__table__.columns:
                    raise ValueError(f"Invalid scope filter column: {col!r}")
                access_clause += f" AND c.{col} = :{col}"
                params[col] = val
        with self.get_session() as session:
            rows = session.execute(
                text(f"""
                    SELECT
                        c.content,
                        d.doc_uuid AS document_id,
                        c.chunk_index,
                        c.section_type,
                        c.parent_heading,
                        ts_rank(
                            to_tsvector('english', c.content),
                            {kw_expr}
                        ) AS rank
                    FROM rag_chunks c
                    JOIN rag_documents d ON c.document_id = d.id
                    WHERE
                        c.collection_name = :collection
                        AND to_tsvector('english', c.content)
                            @@ {kw_expr}
                        {access_clause}
                    ORDER BY rank DESC
                    LIMIT :k
                """),
                params,
            ).fetchall()
            return [
                {
                    "content": row.content,
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "section_type": row.section_type,
                    "parent_heading": row.parent_heading,
                    # Expose the ts_rank score so the retriever can threshold on it.
                    # NOTE: this is Postgres `ts_rank`, not true Okapi BM25 (no k1/b
                    # params, limited length normalization). The project keeps the
                    # `bm25_search` name for historical reasons; treat these scores
                    # as "keyword relevance" rather than textbook BM25. Typical
                    # range is 0.01–0.3 for good matches; zero-token-overlap docs
                    # are excluded by the `@@ plainto_tsquery` filter at SQL level.
                    "score": float(row.rank) if row.rank is not None else 0.0,
                }
                for row in rows
            ]

    def bm25_search_with_filter(self, query: str, collection_name: str,
                                 k: int = 10, metadata_filters: dict | None = None,
                                 allowed_doc_uuids: set[str] | list[str] | None = None,
                                 extra_filters: dict[str, int | str] | None = None) -> List[dict]:
        if allowed_doc_uuids is not None and len(allowed_doc_uuids) == 0:
            return []
        filter_clauses = ""
        kw_expr, kw_params = _keyword_match(query)
        params: dict = {"collection": collection_name, "k": k, **kw_params}
        if metadata_filters:
            clauses = []
            for i, (key, val) in enumerate(metadata_filters.items()):
                if not _METADATA_FILTER_KEY.fullmatch(str(key)):
                    raise ValueError(f"Invalid metadata filter key: {key!r}")
                param_key = f"fval_{i}"
                clauses.append(f"(d.extracted_metadata->>'{key}') = :{param_key}")
                params[param_key] = str(val)
            filter_clauses = "AND " + " AND ".join(clauses)
        if allowed_doc_uuids is not None:
            filter_clauses = (filter_clauses + " " if filter_clauses else "") + \
                "AND d.doc_uuid::text = ANY(:allowed_uuids)"
            params["allowed_uuids"] = [str(u) for u in allowed_doc_uuids]
        # Generic scope filters (see bm25_search): whitelisted column-equality.
        if extra_filters:
            for col, val in extra_filters.items():
                if col not in self.entity.__table__.columns:
                    raise ValueError(f"Invalid scope filter column: {col!r}")
                filter_clauses = (filter_clauses + " " if filter_clauses else "") + \
                    f"AND c.{col} = :{col}"
                params[col] = val
        with self.get_session() as session:
            rows = session.execute(
                text(f"""
                    SELECT
                        c.content,
                        d.doc_uuid AS document_id,
                        c.chunk_index,
                        c.section_type,
                        c.parent_heading,
                        ts_rank(
                            to_tsvector('english', c.content),
                            {kw_expr}
                        ) AS rank
                    FROM rag_chunks c
                    JOIN rag_documents d ON c.document_id = d.id
                    WHERE
                        c.collection_name = :collection
                        AND to_tsvector('english', c.content)
                            @@ {kw_expr}
                        {filter_clauses}
                    ORDER BY rank DESC
                    LIMIT :k
                """),
                params,
            ).fetchall()
            return [
                {
                    "content": row.content,
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "section_type": row.section_type,
                    "parent_heading": row.parent_heading,
                    # Expose the ts_rank score so the retriever can threshold on it.
                    # NOTE: this is Postgres `ts_rank`, not true Okapi BM25 (no k1/b
                    # params, limited length normalization). The project keeps the
                    # `bm25_search` name for historical reasons; treat these scores
                    # as "keyword relevance" rather than textbook BM25. Typical
                    # range is 0.01–0.3 for good matches; zero-token-overlap docs
                    # are excluded by the `@@ plainto_tsquery` filter at SQL level.
                    "score": float(row.rank) if row.rank is not None else 0.0,
                }
                for row in rows
            ]

    def list_by_document_uuid(self, doc_uuid: str, limit: int = 50,
                              offset: int = 0) -> tuple[List[dict], int]:
        """Return (chunks, total_count) for a given document, ordered by chunk_index."""
        with self.get_session() as session:
            total_row = session.execute(
                text("""
                    SELECT COUNT(*) AS n
                    FROM rag_chunks c
                    JOIN rag_documents d ON c.document_id = d.id
                    WHERE d.doc_uuid = :doc_uuid
                """),
                {"doc_uuid": doc_uuid},
            ).fetchone()
            total = int(total_row.n) if total_row else 0

            rows = session.execute(
                text("""
                    SELECT
                        c.chunk_uuid,
                        c.content,
                        c.chunk_index,
                        c.section_type,
                        c.parent_heading,
                        c.collection_name,
                        LENGTH(c.content) AS char_count
                    FROM rag_chunks c
                    JOIN rag_documents d ON c.document_id = d.id
                    WHERE d.doc_uuid = :doc_uuid
                    ORDER BY COALESCE(c.chunk_index, 0), c.id
                    LIMIT :limit OFFSET :offset
                """),
                {"doc_uuid": doc_uuid, "limit": limit, "offset": offset},
            ).fetchall()
            return [
                {
                    "chunk_id": str(row.chunk_uuid),
                    "content": row.content,
                    "chunk_index": row.chunk_index,
                    "section_type": row.section_type,
                    "parent_heading": row.parent_heading,
                    "collection_name": row.collection_name,
                    "char_count": int(row.char_count or 0),
                }
                for row in rows
            ], total

    def count_by_collection(self, collection_name: str) -> int:
        with self.get_session() as session:
            return session.query(self.entity).filter(
                self.entity.collection_name == collection_name
            ).count()

    def create_fts_index(self) -> None:
        with self.sql_connector.engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_rag_chunks_fts "
                "ON rag_chunks USING GIN(to_tsvector('english', content))"
            ))
            conn.commit()
