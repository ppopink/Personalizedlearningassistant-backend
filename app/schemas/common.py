from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class RagSummary(BaseModel):
    document_topic: Optional[str] = None
    document_keywords: List[str] = Field(default_factory=list)
    document_abstract: Optional[str] = None

