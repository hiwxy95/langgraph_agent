from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, delete, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.rag.categories import category_label, validate_category
from app.rag.embeddings import DashScopeEmbeddingClient
from app.rag.text_splitter import split_text


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    category: str
    category_label: str
    chunk_index: int
    content: str
    similarity: float
    source_name: str | None = None
    source_url: str | None = None

    def as_source(self) -> dict[str, Any]:
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "title": self.title,
            "category": self.category,
            "category_label": self.category_label,
            "chunk_index": self.chunk_index,
            "similarity": round(self.similarity, 4),
            "source_name": self.source_name,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class RagContext:
    text: str
    sources: list[dict[str, Any]]
    chunks: list[RetrievedChunk]


class KnowledgeService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_client: DashScopeEmbeddingClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_client = embedding_client or DashScopeEmbeddingClient(self.settings)

    async def ingest_text(
        self,
        *,
        title: str,
        category: str,
        content: str,
        source_type: str = "text",
        source_name: str | None = None,
        source_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeDocument:
        category = validate_category(category)
        title = title.strip()
        content = content.strip()
        if not title:
            raise ValueError("Title is required.")
        if not content:
            raise ValueError("Document content is empty.")

        chunks = split_text(content)
        if not chunks:
            raise ValueError("Document content is empty after splitting.")

        embeddings = await self.embedding_client.embed_documents(chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding count does not match chunk count.")

        document = KnowledgeDocument(
            title=title,
            category=category,
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            content=content,
            status="active",
            document_metadata={
                "chunk_count": len(chunks),
                "embedding_model": self.settings.dashscope_embedding_model,
                **(metadata or {}),
            },
        )
        self.session.add(document)
        await self.session.flush()

        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            await self.session.execute(
                text(
                    """
                    INSERT INTO knowledge_chunks
                        (id, document_id, chunk_index, content, embedding, chunk_metadata)
                    VALUES
                        (:id, :document_id, :chunk_index, :content,
                         CAST(:embedding AS vector), CAST(:chunk_metadata AS jsonb))
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "document_id": document.id,
                    "chunk_index": index,
                    "content": chunk,
                    "embedding": vector_literal(embedding),
                    "chunk_metadata": '{"splitter":"paragraph_overlap"}',
                },
            )

        await self.session.commit()
        await self.session.refresh(document)
        return document

    async def list_documents(
        self, category: str | None = None, q: str | None = None
    ) -> list[tuple[KnowledgeDocument, int]]:
        stmt: Select[Any] = (
            select(KnowledgeDocument, func.count(KnowledgeChunk.id))
            .outerjoin(KnowledgeChunk)
            .group_by(KnowledgeDocument.id)
            .order_by(desc(KnowledgeDocument.updated_at))
        )
        if category:
            stmt = stmt.where(KnowledgeDocument.category == validate_category(category))
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    KnowledgeDocument.title.ilike(pattern),
                    KnowledgeDocument.content.ilike(pattern),
                    KnowledgeDocument.source_name.ilike(pattern),
                )
            )
        rows = await self.session.execute(stmt)
        return [(document, int(chunk_count)) for document, chunk_count in rows.all()]

    async def get_document(self, document_id: uuid.UUID) -> KnowledgeDocument | None:
        stmt = (
            select(KnowledgeDocument)
            .options(selectinload(KnowledgeDocument.chunks))
            .where(KnowledgeDocument.id == document_id)
        )
        return await self.session.scalar(stmt)

    async def delete_document(self, document_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def search(
        self, query: str, category: str | None = None, top_k: int | None = None
    ) -> list[RetrievedChunk]:
        query = query.strip()
        if not query:
            return []
        if category:
            category = validate_category(category)
        top_k = max(1, min(top_k or self.settings.rag_top_k, 20))
        query_embedding = await self.embedding_client.embed_query(query)

        category_filter = "AND d.category = :category" if category else ""
        rows = await self.session.execute(
            text(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id AS document_id,
                    d.title AS title,
                    d.category AS category,
                    c.chunk_index AS chunk_index,
                    c.content AS content,
                    d.source_name AS source_name,
                    d.source_url AS source_url,
                    1 - (c.embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE d.status = 'active'
                {category_filter}
                ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
                LIMIT :top_k
                """
            ),
            {
                "query_embedding": vector_literal(query_embedding),
                "category": category,
                "top_k": top_k,
            },
        )

        return [
            RetrievedChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                title=row.title,
                category=row.category,
                category_label=category_label(row.category),
                chunk_index=int(row.chunk_index),
                content=row.content,
                similarity=float(row.similarity or 0),
                source_name=row.source_name,
                source_url=row.source_url,
            )
            for row in rows
        ]

    async def has_active_documents(self) -> bool:
        count = await self.session.scalar(
            select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.status == "active")
        )
        return bool(count)


def build_rag_context(chunks: list[RetrievedChunk]) -> RagContext:
    if not chunks:
        return RagContext(text="", sources=[], chunks=[])

    sections: list[str] = []
    sources: list[dict[str, Any]] = []
    for number, chunk in enumerate(chunks, start=1):
        source = chunk.as_source()
        source["ref"] = number
        sources.append(source)
        sections.append(
            "\n".join(
                [
                    f"[{number}] {chunk.title} / {chunk.category_label} / 片段 {chunk.chunk_index + 1}",
                    chunk.content,
                ]
            )
        )
    return RagContext(text="\n\n".join(sections), sources=sources, chunks=chunks)


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"
