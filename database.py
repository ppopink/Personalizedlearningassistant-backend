from app.db.models import (
    CognitiveProfileObservation,
    InterviewMessage,
    InterviewResult,
    InterviewSession,
    KnowledgeMastery,
    User,
    UserCognitiveProfile,
    UserLearningProgress,
    UserNote,
    UserSyllabus,
)
from app.db.session import Base, SessionLocal, engine, init_db


__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "init_db",
    "User",
    "KnowledgeMastery",
    "UserSyllabus",
    "UserNote",
    "InterviewSession",
    "InterviewMessage",
    "InterviewResult",
    "UserCognitiveProfile",
    "CognitiveProfileObservation",
    "UserLearningProgress",
]


if __name__ == "__main__":
    init_db()
    print("数据库 ai_tutor.db 初始化成功！")
