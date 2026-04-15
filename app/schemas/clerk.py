from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ChatMessage


class ClerkGenerateNoteRequest(BaseModel):
    user_id: str
    course_id: str
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    note_title: Optional[str] = None
    focus_questions: List[str] = Field(default_factory=list)
    messages: List[ChatMessage] = Field(default_factory=list)
    user_takeaways: str = ""
    additional_context: str = ""
    auto_save: bool = False
    include_mindmap: bool = True
