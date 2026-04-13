# 🧠 Personalized Learning Assistant - AI Backend

这是“个性化 AI 专属私教”项目的核心后端服务。它基于 **FastAPI** 和 **大语言模型 (LLM)** 构建，致力于提供从结构化学习大纲生成、实时 AI 陪伴辅导、到结构化思维导图复盘笔记的一站式智能化学习体验。

## ✨ 核心特性

本后端不仅仅是简单的 LLM 接口转发层，而是深度结合了教育业务场景的**智能中枢**：

1. **持久化 AI 记忆引擎 (SQLite + SQLAlchemy)**
   - 打破了“聊完即忘”的模型限制，将用户的背景信息、学习进度和薄弱知识点持久化存储在数据库中。
   - 实现**上下文感知 (Context-Aware)**，AI 在辅导时能动态调整策略，真正做到因材施教。
   
2. **结构化“定制大纲”生成引擎 (`/api/onboarding/generate-syllabus`)**
   - 通过强制 JSON 模式（JSON Mode），引导大模型将泛泛而谈的学习建议，转化为前端可直接渲染的多级嵌套树状结构（包含章节和具体知识点），并自动落库持久化。
   
3. **“千人千面”私教聊天室 (`/api/study/tutor-chat/stream`)**
   - **流式输出 (SSE)**：打字机效果，极致的用户体验。
   - **动态人设注入**：支持三种导师风格：🤗 **鼓励引导型**、🎯 **精炼直接型**、😄 **幽默风趣型**。
   - **防作弊机制**：高度约束提示词，私教会一步步给出解题 Hint，坚决杜绝直接给出最终答案。
   
4. **一键智能复盘与脑图引擎 (`/api/notes/generate` & `/api/notes/extract-mindmap`)**
   - **AI 复盘笔记**：结合用户学习历史和易错点，自动生成包含干货、避坑指南的结构化 Markdown 笔记。
   - **Mermaid 脑图融合**：使用业界标杆的 `Mermaid.js` 语法规则直接在笔记末尾生成可视化的思维导图代码（严格的鲁棒性双引号语法保护）。
   - **提炼图纸**：支持单独提供文本，一键精炼萃取 Mermaid 脑图代码块。

## 📁 核心目录结构

```text
.
├── main.py               # 🚀 FastAPI 应用主入口、路由分发、业务逻辑与所有核心 Prompt
├── database.py           # 🗄️ SQLAlchemy 数据模型层定义 (User, KnowledgeMastery, UserSyllabus)
├── ai_tutor.db           # 💾 SQLite 持久化本地数据库文件 (自动生成)
├── requirements.txt      # 📦 依赖清单 (fastapi, uvicorn, openai, sqlalchemy 等)
└── .env                  # 🔑 环境变量配置 (存储大模型 API Key)
```

## 🚀 快速启动

**1. 准备环境**

确保你的电脑已经安装了 `Python 3.8+`。

```bash
# 激活虚拟环境 (可选，但强烈推荐)
source venv/bin/activate
# 安装核心依赖
pip install -r requirements.txt
```

**2. 配置密钥**

在根目录下创建（或修改） `.env` 文件，填入你的大模型 API 密钥（目前默认使用兼容 OpenAI API 格式的通义千问 `qwen-plus`）：

```env
QWEN_API_KEY=sk-xxxxxx...
```

**3. 启动服务**

```bash
uvicorn main:app --reload
```

> 🌟 服务启动后，核心服务运行在：`http://127.0.0.1:8000`

## 🔌 API 接口全景概览

### 1️⃣ 用户数据与“记忆”
- `POST /api/user/profile` — 更新/创建用户学习背景资料（基础、目标等）。
- `POST /api/knowledge/update` — 更新用户对特定知识点的掌握程度和易错总结。
- `POST /api/interview/start` — 启动 Agent 1 访谈会话，生成第一条“单次单问”问题。
- `POST /api/interview/reply` — 用户回复访谈内容，后端更新槽位并返回下一问或访谈总结。
- `GET /api/interview/{session_id}` — 获取一轮完整访谈的上下文、消息记录和结构化结果。

### 2️⃣ 课程与大纲
- `POST /api/architect/generate-course-plan` — 启动 Agent 2，读取访谈结果并生成章节、学习目标和练习题一体化课程蓝图。
- `POST /api/onboarding/generate-syllabus` — 🎲 **核心**：根据用户输入生成 JSON 定制学习路径并保存。
- `GET /api/curriculum/{user_id}/{course_id}` — 从数据库读取已生成的专属学习大纲。

### 3️⃣ AI 学习辅导
- `POST /api/tutor/respond` — Agent 3 非流式调试接口，读取课程蓝图、学习者画像和思维方式脚本后返回陪伴式指导。
- `POST /api/study/tutor-chat/stream` — 💡 **核心**：Agent 3 流式陪伴导师接口，支持当前章节、小节、题目上下文、导师风格和思维脚本驱动的苏格拉底式引导。

### 4️⃣ 认知画像
- `POST /api/profiler/analyze-interaction` — Agent 4 静默分析一次学习交互，提炼偏好、卡点与激励点，并更新用户思维画像。
- `GET /api/profiler/profile/{user_id}` — 查看用户当前思维画像和最近几次认知观察记录。

### 5️⃣ 复盘与思维导图
- `POST /api/clerk/generate-note` — Agent 5 读取当前章节、最近交互和认知画像，生成智能笔记与 Mermaid 脑图，并可选自动保存。
- `POST /api/notes/generate` — 📝 **核心**：提交已学内容和薄弱点，一键生成带有 Mermaid 思维导图的高质量复盘笔记。
- `POST /api/notes/extract-mindmap` — 🗺️ 提交任意长文本内容，AI 高度提炼精简并返回单纯的 Mermaid 思维导图代码。

### 6️⃣ 全局助手
- `POST /api/progress/update` — 上报当前课程、章节、小节与完成情况，供全局助手和进度查询使用。
- `GET /api/progress/{user_id}` — 查询用户全部课程进度；支持通过 `course_id` 查询单门课详细进度。
- `POST /api/concierge/respond` — Agent 6 全局助手接口，读取进度、课程、笔记和画像后返回平台导航或全局答复，并可携带前端动作建议。

---
*“技术是骨架，Prompt 是灵魂，数据是流淌的血肉。”* —— 一款真正有温度的学习工具产品。
