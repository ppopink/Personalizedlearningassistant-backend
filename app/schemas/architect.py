from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import RagSummary


class ArchitectConfig(BaseModel):
    chapter_count: int = 4
    min_sections_per_chapter: int = 2
    max_sections_per_chapter: int = 4
    questions_per_section: int = 2


class ArchitectGenerateRequest(BaseModel):
    user_id: str
    course_id: str
    course_type: Optional[str] = None
    course_title: Optional[str] = None
    course_summary: Optional[str] = None
    key_topics: List[str] = Field(default_factory=list)
    rag_summary: Optional[RagSummary] = None
    interview_session_id: Optional[str] = None
    interview_result: Optional[Dict[str, Any]] = None
    architect_config: ArchitectConfig = Field(default_factory=ArchitectConfig)
