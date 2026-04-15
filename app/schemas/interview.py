from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import RagSummary


class InterviewConfig(BaseModel):
    max_questions: int = 6
    target_duration_min: int = 3
    ask_one_question_only: bool = True


class StartInterviewRequest(BaseModel):
    user_id: str
    course_id: str
    course_type: str = "standard"
    course_title: Optional[str] = None
    course_summary: Optional[str] = None
    key_topics: List[str] = Field(default_factory=list)
    rag_summary: Optional[RagSummary] = None
    history_profile: Dict[str, Any] = Field(default_factory=dict)
    interview_config: InterviewConfig = Field(default_factory=InterviewConfig)


class ReplyInterviewRequest(BaseModel):
    session_id: str
    user_message: str
