from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import ALLOWED_ORIGINS
from app.db.session import init_db
from app.routers.agent import router as agent_router
from app.routers.architect import router as architect_router
from app.routers.clerk import router as clerk_router
from app.routers.concierge import router as concierge_router
from app.routers.course_management import router as course_management_router
from app.routers.interview import router as interview_router
from app.routers.notes import router as notes_router
from app.routers.profiler import router as profiler_router
from app.routers.progress import router as progress_router
from app.routers.study import router as study_router
from app.routers.tutor import router as tutor_router
from app.routers.user import router as user_router


app = FastAPI(title="AI 编程私教 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


app.include_router(agent_router)
app.include_router(user_router)
app.include_router(interview_router)
app.include_router(architect_router)
app.include_router(tutor_router)
app.include_router(profiler_router)
app.include_router(clerk_router)
app.include_router(progress_router)
app.include_router(concierge_router)
app.include_router(course_management_router)
app.include_router(notes_router)
app.include_router(study_router)


@app.get("/")
async def root():
    return {"message": "AI 后端服务已启动！"}
