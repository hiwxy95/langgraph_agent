import uuid

import pytest

from app.agent.graph import TravelAgent
from app.rag.loaders import load_document_bytes
from app.rag.service import RetrievedChunk, build_rag_context, vector_literal
from app.rag.text_splitter import split_text


def test_split_text_keeps_content_and_creates_overlap_chunks() -> None:
    text = "A" * 500 + "\n\n" + "B" * 500 + "\n\n" + "C" * 500

    chunks = split_text(text, chunk_size=700, overlap=80)

    assert len(chunks) >= 3
    joined = "\n".join(chunks)
    assert "A" * 120 in joined
    assert "B" * 120 in joined
    assert "C" * 120 in joined


def test_split_text_returns_empty_for_blank_input() -> None:
    assert split_text(" \n\n ") == []


def test_loader_rejects_unsupported_files() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_document_bytes("notice.xlsx", b"content")


def test_build_rag_context_formats_sources() -> None:
    chunk = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        title="广东省文旅政策",
        category="policy_document",
        category_label="政策文档",
        chunk_index=0,
        content="鼓励开发岭南文化旅游线路。",
        similarity=0.91,
    )

    context = build_rag_context([chunk])

    assert "[1] 广东省文旅政策 / 政策文档 / 片段 1" in context.text
    assert context.sources[0]["title"] == "广东省文旅政策"
    assert context.sources[0]["ref"] == 1


def test_vector_literal_uses_pgvector_format() -> None:
    assert vector_literal([0.1, -0.25]) == "[0.10000000,-0.25000000]"


def test_agent_metadata_can_read_knowledge_sources() -> None:
    response = TravelAgent._to_response(
        {
            "conversation_id": "conversation-1",
            "messages": [],
            "knowledge_context": {
                "sources": [{"title": "景区介绍", "chunk_index": 0}],
            },
        }
    )

    assert response["status"] == "completed"
