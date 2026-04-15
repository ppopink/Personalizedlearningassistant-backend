# Personalized Learning Assistant Backend

这是智能学习平台的后端服务，基于 `FastAPI + SQLAlchemy + Qwen(OpenAI 兼容接口)` 构建。  
当前版本已经完成从“单文件巨石”到“模块化后端”的重构，核心 6 个 Agent 和普通业务接口都已拆分到 `app/` 目录下。

## 当前能力

- Agent 1 `Interviewer`：课前访谈，输出结构化访谈结果
- Agent 2 `Architect`：根据访谈结果生成课程蓝图
- Agent 3 `Tutor`：带课程上下文和思维脚本的陪伴导师
- Agent 4 `Profiler`：把对话沉淀为认知画像
- Agent 5 `Clerk`：生成智能笔记和 Mermaid 脑图
- Agent 6 `Concierge`：全局助手、进度反馈与前端动作建议
- 用户资料、笔记、课程、自定义课程、学习题生成等普通业务接口

## 项目结构

```text
.
├── main.py                  # 仅保留 FastAPI 入口、CORS、startup、router 注册
├── database.py              # 兼容层，转发到 app/db/*
├── requirements.txt
├── tests/
│   └── test_app_smoke.py    # 基础 smoke tests
└── app/
    ├── core/
    │   ├── config.py        # 环境变量、LLM client、CORS 配置
    │   └── deps.py          # get_db 等依赖
    ├── db/
    │   ├── models.py        # SQLAlchemy ORM 模型
    │   └── session.py       # engine / SessionLocal / init_db
    ├── schemas/             # Pydantic 请求模型
    ├── services/            # 业务逻辑、Prompt 调用、流程编排
    └── routers/             # API 路由定义
```

## 启动方式

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

在项目根目录创建 `.env`：

```env
QWEN_API_KEY=your_qwen_api_key
```

可选数据库配置：

```env
DATABASE_URL=sqlite:///./ai_tutor.db
```

如果不提供 `DATABASE_URL`，默认使用本地 `SQLite`。

### 3. 启动服务

```bash
uvicorn main:app --reload
```

服务默认运行在：

```text
http://127.0.0.1:8000
```

## 测试

当前仓库已补充基础 smoke tests，用来验证：

- 应用可以正常导入
- 根路由可访问
- 核心 API 路由都已注册

运行方式：

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## 核心接口分组

### Agent

- `POST /api/interview/start`
- `POST /api/interview/reply`
- `GET /api/interview/{session_id}`
- `POST /api/architect/generate-course-plan`
- `POST /api/tutor/respond`
- `POST /api/study/tutor-chat/stream`
- `POST /api/profiler/analyze-interaction`
- `GET /api/profiler/profile/{user_id}`
- `POST /api/clerk/generate-note`
- `POST /api/concierge/respond`

### 学习进度与课程

- `POST /api/progress/update`
- `GET /api/progress/{user_id}`
- `POST /api/onboarding/generate-syllabus`
- `POST /api/onboarding/generate-custom-syllabus`
- `GET /api/curriculum/{user_id}/{course_id}`
- `GET /api/user/custom-courses/{user_id}`
- `DELETE /api/user/custom-courses/{course_id}`

### 用户与笔记

- `POST /api/user/profile`
- `POST /api/knowledge/update`
- `POST /api/notes/generate`
- `POST /api/notes/extract-mindmap`
- `POST /api/notes/save`
- `GET /api/notes/list/{user_id}`

### 其他

- `POST /api/agent/chat`
- `POST /api/agent/chat/stream`
- `POST /api/study/generate-questions`

## 当前状态

- `main.py` 已从近 `3000` 行缩减到轻量入口
- 核心 Agent 已全部模块化
- 数据模型、Schema、Router、Service 已分层
- 已补基础 smoke tests

## 下一步建议

- 补每个 Agent 的单元测试和 mock LLM 测试
- 为数据库引入 migrations
- 统一 README 与接口文档
- 逐步给前端补字段对接文档和联调示例
