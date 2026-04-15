from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ChatMessage


class ProfilerAnalyzeRequest(BaseModel):
    user_id: str
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    interaction_type: str = "tutor_dialogue"
    tutor_style: Optional[str] = None
    question_context: str = ""
    user_action: str = ""
    user_message: str = ""
    tutor_reply: str = ""
    user_feedback: str = ""
    messages: List[ChatMessage] = Field(default_factory=list)
    thinking_script_snapshot: Optional[Dict[str, Any]] = None
    learner_profile_snapshot: Optional[Dict[str, Any]] = None
