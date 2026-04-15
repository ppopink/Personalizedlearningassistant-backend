from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import KnowledgeMastery, User
from app.schemas.user import MasteryUpdateRequest, UserProfileRequest


def update_user_profile_flow(request: UserProfileRequest, db: Session):
    user = db.query(User).filter(User.username == request.username).first()
    if not user:
        user = User(username=request.username)
        db.add(user)

    user.background = request.background
    user.daily_goal_minutes = request.daily_goal_minutes
    db.commit()
    return {"status": "success", "message": "用户信息已更新"}


def update_knowledge_mastery_flow(request: MasteryUpdateRequest, db: Session):
    user = db.query(User).filter(User.username == request.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    record = db.query(KnowledgeMastery).filter(
        KnowledgeMastery.user_id == user.id,
        KnowledgeMastery.point_name == request.point_name,
    ).first()

    if not record:
        record = KnowledgeMastery(user_id=user.id, point_name=request.point_name)
        db.add(record)

    record.mastery_score = request.mastery_score
    record.error_summary = request.error_summary
    db.commit()
    return {"status": "success", "message": f"{request.point_name} 的掌握度已更新"}
