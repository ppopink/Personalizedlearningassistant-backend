import os
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, JSON, Text, DateTime
from datetime import datetime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 🚨 核心修改：优先读取环境变量 DATABASE_URL
# 如果在本地找不到环境变量，就自动降级使用本地的 sqlite
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# 兼容 Render/Heroku 的 postgres:// 协议
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 如果环境变量为空，则使用本地 SQLite
if not SQLALCHEMY_DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./ai_tutor.db"

# 创建数据库引擎
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建模型基类
Base = declarative_base()

# 1. 用户基础信息表
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    background = Column(String)
    daily_goal_minutes = Column(Integer)

# 2. 知识点掌握度表
class KnowledgeMastery(Base):
    __tablename__ = "knowledge_mastery"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    point_name = Column(String, index=True)
    mastery_score = Column(Integer, default=0)
    error_summary = Column(String)

# 3. 核心模型：用户学习大纲表
class UserSyllabus(Base):
    __tablename__ = "user_syllabus"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)    # 用户ID
    course_id = Column(String, index=True)  # 课程ID
    syllabus_data = Column(JSON)            # 直接存储 AI 生成的 JSON 数据

# 4. 🚨 新增：用户笔记表
class UserNote(Base):
    __tablename__ = "user_notes"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)        # 谁写的笔记
    course_id = Column(String, index=True)      # 是在哪门课写的笔记
    title = Column(String)                      # 笔记标题
    content = Column(Text)                      # 笔记正文内容
    created_at = Column(DateTime, default=datetime.utcnow) # 创建时间


# 初始化数据库并建表
def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("数据库 ai_tutor.db 初始化成功！")
