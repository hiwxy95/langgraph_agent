from __future__ import annotations

from typing import Literal

KnowledgeCategory = Literal[
    "tourism_material",
    "policy_document",
    "attraction_intro",
    "hotel_description",
]

KNOWLEDGE_CATEGORIES: dict[str, str] = {
    "tourism_material": "文旅资料",
    "policy_document": "政策文档",
    "attraction_intro": "景区介绍",
    "hotel_description": "酒店说明",
}


def validate_category(category: str) -> KnowledgeCategory:
    if category not in KNOWLEDGE_CATEGORIES:
        allowed = ", ".join(KNOWLEDGE_CATEGORIES)
        raise ValueError(f"Unsupported knowledge category: {category}. Allowed: {allowed}.")
    return category  # type: ignore[return-value]


def category_label(category: str) -> str:
    return KNOWLEDGE_CATEGORIES.get(category, category)
