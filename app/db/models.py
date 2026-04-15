from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from app.db.session import Base


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    background = Column(String)
    daily_goal_minutes = Column(Integer)


class KnowledgeMastery(Base):
    __tablename__ = "knowledge_mastery"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    point_name = Column(String, index=True)
    mastery_score = Column(Integer, default=0)
    error_summary = Column(String)


class UserSyllabus(Base):
    __tablename__ = "user_syllabus"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    course_id = Column(String, index=True)
    syllabus_data = Column(JSON)


class UserNote(Base):
    __tablename__ = "user_notes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    course_id = Column(String, index=True)
    title = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=utc_now)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    course_id = Column(String, index=True, nullable=False)
    course_type = Column(String, default="standard")
    status = Column(String, default="active")
    question_count = Column(Integer, default=0)
    max_questions = Column(Integer, default=6)
    context_data = Column(JSON)
    slot_state = Column(JSON)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class InterviewMessage(Base):
    __tablename__ = "interview_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("interview_sessions.id"), index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)


class InterviewResult(Base):
    __tablename__ = "interview_results"

    session_id = Column(String, ForeignKey("interview_sessions.id"), primary_key=True)
    result_json = Column(JSON)
    termination_reason = Column(String)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class UserCognitiveProfile(Base):
    __tablename__ = "user_cognitive_profiles"

    user_id = Column(String, primary_key=True, index=True)
    profile_json = Column(JSON)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class CognitiveProfileObservation(Base):
    __tablename__ = "cognitive_profile_observations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    course_id = Column(String, index=True)
    chapter_id = Column(String, index=True)
    section_id = Column(String, index=True)
    interaction_type = Column(String, default="tutor_dialogue")
    observation_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now)


class UserLearningProgress(Base):
    __tablename__ = "user_learning_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    course_id = Column(String, index=True, nullable=False)
    current_chapter_id = Column(String, index=True)
    current_chapter_title = Column(String)
    current_section_id = Column(String, index=True)
    current_section_title = Column(String)
    completed_chapter_ids = Column(JSON)
    completed_section_ids = Column(JSON)
    progress_json = Column(JSON)
    last_activity_at = Column(DateTime, default=utc_now, onupdate=utc_now)
