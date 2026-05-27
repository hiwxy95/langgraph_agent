from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    KnowledgeCategory,
    KnowledgeChunkOut,
    KnowledgeDocumentCreate,
    KnowledgeDocumentDetailOut,
    KnowledgeDocumentOut,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.db.session import get_session
from app.rag.loaders import load_document_bytes
from app.rag.service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/documents", response_model=KnowledgeDocumentOut)
async def create_document(
    request: KnowledgeDocumentCreate,
    session: AsyncSession = Depends(get_session),
) -> KnowledgeDocumentOut:
    try:
        document = await KnowledgeService(session).ingest_text(
            title=request.title,
            category=request.category,
            content=request.content,
            source_type="text",
            source_url=request.source_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _document_out(document, _chunk_count(document))


@router.post("/documents/upload", response_model=KnowledgeDocumentOut)
async def upload_document(
    title: str = Form(...),
    category: KnowledgeCategory = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeDocumentOut:
    data = await file.read()
    try:
        content = load_document_bytes(file.filename or title, data)
        document = await KnowledgeService(session).ingest_text(
            title=title,
            category=category,
            content=content,
            source_type="upload",
            source_name=file.filename,
            metadata={"content_type": file.content_type},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _document_out(document, _chunk_count(document))


@router.get("/documents", response_model=list[KnowledgeDocumentOut])
async def list_documents(
    category: KnowledgeCategory | None = Query(default=None),
    q: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeDocumentOut]:
    rows = await KnowledgeService(session).list_documents(category=category, q=q)
    return [_document_out(document, chunk_count) for document, chunk_count in rows]


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentDetailOut)
async def get_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> KnowledgeDocumentDetailOut:
    document = await KnowledgeService(session).get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")
    return KnowledgeDocumentDetailOut(
        **_document_out(document, len(document.chunks)).model_dump(),
        content=document.content,
        chunks=[_chunk_out(chunk) for chunk in document.chunks],
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    deleted = await KnowledgeService(session).delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")


@router.post("/search", response_model=list[KnowledgeSearchResult])
async def search_knowledge(
    request: KnowledgeSearchRequest,
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeSearchResult]:
    chunks = await KnowledgeService(session).search(
        request.query, category=request.category, top_k=request.top_k
    )
    return [
        KnowledgeSearchResult(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            title=chunk.title,
            category=chunk.category,  # type: ignore[arg-type]
            category_label=chunk.category_label,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            similarity=chunk.similarity,
            source_name=chunk.source_name,
            source_url=chunk.source_url,
        )
        for chunk in chunks
    ]


def _document_out(document: KnowledgeDocument, chunk_count: int) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut(
        id=document.id,
        title=document.title,
        category=document.category,  # type: ignore[arg-type]
        source_type=document.source_type,
        source_name=document.source_name,
        source_url=document.source_url,
        status=document.status,
        chunk_count=chunk_count,
        metadata=document.document_metadata or {},
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _chunk_out(chunk: KnowledgeChunk) -> KnowledgeChunkOut:
    return KnowledgeChunkOut(
        id=chunk.id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        metadata=chunk.chunk_metadata or {},
        created_at=chunk.created_at,
    )


def _chunk_count(document: KnowledgeDocument) -> int:
    metadata_count = (document.document_metadata or {}).get("chunk_count")
    if isinstance(metadata_count, int):
        return metadata_count
    return len(getattr(document, "chunks", []) or [])
