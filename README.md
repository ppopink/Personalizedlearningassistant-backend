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

### 2️⃣ 课程与大纲
- `POST /api/onboarding/generate-syllabus` — 🎲 **核心**：根据用户输入生成 JSON 定制学习路径并保存。
- `GET /api/curriculum/{user_id}/{course_id}` — 从数据库读取已生成的专属学习大纲。

### 3️⃣ AI 学习辅导
- `POST /api/study/tutor-chat/stream` — 💡 **核心**：发起一场流式对话流，传入当前题目信息、用户提问，以及期望的导师风格（`encouraging`, `concise`, `humorous`），获取专属指导。

### 4️⃣ 复盘与思维导图
- `POST /api/notes/generate` — 📝 **核心**：提交已学内容和薄弱点，一键生成带有 Mermaid 思维导图的高质量复盘笔记。
- `POST /api/notes/extract-mindmap` — 🗺️ 提交任意长文本内容，AI 高度提炼精简并返回单纯的 Mermaid 思维导图代码。

---
*“技术是骨架，Prompt 是灵魂，数据是流淌的血肉。”* —— 一款真正有温度的学习工具产品。
