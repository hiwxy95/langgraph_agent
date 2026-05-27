# 文旅 AI 智能体

前后端分离的 LangGraph 文旅智能体示例：

- 后端：FastAPI + LangGraph + PostgreSQL checkpointer
- 模型：DeepSeek 与通义千问 OpenAI-compatible API 统一封装，支持动态路由
- 地图：高德地图官方 MCP Streamable HTTP 服务
- 前端：Vue 3 + Vite 对话式界面，支持 human-in-the-loop 确认

## 目录

```text
backend/   FastAPI、LangGraph、数据库、模型路由、高德 MCP
frontend/  Vue 对话界面
```

## 后端启动

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `backend/.env`：

- `DATABASE_URL`：业务表连接，格式如 `postgresql+asyncpg://user:pass@host:5432/db`
- `CHECKPOINT_DATABASE_URL`：LangGraph checkpoint 连接，格式如 `postgresql://user:pass@host:5432/db`
- `DEEPSEEK_API_KEY`
- `DASHSCOPE_API_KEY`
- `AMAP_MAPS_API_KEY`

初始化数据库：

```powershell
python -m scripts.init_db
```

启动服务：

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8011
```

## 前端启动

PowerShell 默认策略可能拦截 `npm.ps1`，建议使用 `npm.cmd`：

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

访问 `http://localhost:5173`。

## API

- `POST /api/conversations`：新建对话
- `GET /api/conversations`：对话列表
- `GET /api/conversations/{id}`：对话详情
- `POST /api/conversations/{id}/messages`：发送消息并触发 Agent
- `POST /api/conversations/{id}/approvals`：提交人工确认并恢复 Agent

## 行为说明

- 默认模型路由为质量优先：复杂规划和 ReAct 推理走 DeepSeek，普通闲聊和单次查询走通义千问。
- 酒店查询基于高德 POI，不提供实时房价、房态或预订能力。
- 高德 MCP 工具名可通过 `AMAP_ROUTE_TOOL`、`AMAP_HOTEL_TOOL`、`AMAP_ATTRACTION_TOOL` 覆盖；不配置时后端会按工具名和描述做关键词匹配。
- 发送文旅规划需求后，Agent 会生成草案并触发 human-in-the-loop；前端确认后继续生成最终方案。
