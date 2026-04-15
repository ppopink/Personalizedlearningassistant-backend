from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.common import ChatMessage


class TutorRequest(BaseModel):
    messages: List[ChatMessage]
    question_context: str = ""
    user_action: str = ""
    tutor_style: str = "鼓励引导型"
    user_id: Optional[str] = None
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    difficulty_preference: Optional[str] = None
    thinking_script: Optional[Dict[str, Any]] = None
