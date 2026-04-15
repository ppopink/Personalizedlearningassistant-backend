from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.agent import ChatRequest
from app.services.agent_service import chat_with_agent_flow, chat_with_agent_stream_flow


router = APIRouter(tags=["agent"])


@router.post("/api/agent/chat")
async def chat_with_agent(request: ChatRequest, db: Session = Depends(get_db)):
    return chat_with_agent_flow(request, db)


@router.post("/api/agent/chat/stream")
async def chat_with_agent_stream(request: ChatRequest, db: Session = Depends(get_db)):
    return chat_with_agent_stream_flow(request, db)
