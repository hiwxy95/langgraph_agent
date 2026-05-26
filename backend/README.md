# Backend 说明

## 1. 后台整体是做什么的

这个 backend 是一个基于 FastAPI 的“广东文旅 AI 智能体”服务端，主要负责三件事：

1. 对外提供对话接口，给前端创建会话、发送消息、拉取历史记录。
2. 调用 LangGraph + LLM 组织智能体推理流程，生成旅游草案、等待人工确认、再输出最终结果。
3. 把会话、消息、人工审批记录保存到 PostgreSQL，并使用 LangGraph 的 checkpoint 能力保存智能体执行状态。

从职责上看，它不是一个单纯的聊天接口，而是一个“带状态的旅游规划后端”。

---

## 2. 核心执行流程

### 2.1 应用入口

应用入口在 [app/main.py](app/main.py)。

这里做了几件基础工作：
- 创建 FastAPI 应用
- 配置 CORS，允许前端本地开发地址访问
- 挂载对话路由
- 提供 `/health` 健康检查接口

也就是说，前端请求真正进入业务逻辑时，首先会从这里注册的路由进入。

### 2.2 一次用户消息是怎么被处理的

核心接口在 [app/api/conversations.py](app/api/conversations.py)。

以 `POST /conversations/{conversation_id}/messages` 为例，流程大致是：

1. 校验会话是否存在。
2. 先把用户消息写入数据库。
3. 创建 `TravelAgent` 实例。
4. 调用智能体执行：`agent.run(...)` 或流式版本 `agent.run_stream(...)`。
5. 把智能体返回的 AI 消息写回数据库。
6. 如果结果需要人工确认，则创建一条审批记录。
7. 返回普通响应，或者通过 SSE 持续把 token / message / approval / done 事件推给前端。

这个文件承担的是“API 编排层”的职责：
- 接 FastAPI 请求
- 调仓储层读写数据库
- 调智能体层执行推理
- 把结果转成前端能消费的响应结构

### 2.3 智能体内部怎么走

智能体主逻辑在 [app/agent/graph.py](app/agent/graph.py)。

这个类把 LangGraph 工作流组织成了一条状态机，大致分成这几个阶段：

1. **classify_input**
   - 先判断用户消息是不是旅游规划类请求。
   - 如果消息里有“路线、规划、行程、酒店、景点、旅游”等关键词，就走规划链路。
   - 否则走普通聊天链路。

2. **react_reasoning**
   - 如果判断为规划任务，就加载高德 MCP 工具。
   - 使用 ReAct agent 决定要不要调用路线、酒店、景点等工具。
   - 把工具结果整理到 `tool_results` 中。

3. **draft_itinerary**
   - 基于用户历史消息和工具查询结果，让大模型生成一版“待确认草案”。
   - 草案会写进 `pending_approval`，等待人工确认。

4. **human_review**
   - 通过 LangGraph 的 `interrupt(...)` 中断工作流。
   - 等用户在前端点“确认 / 修改 / 取消”后再恢复执行。

5. **final_response**
   - 如果用户确认或补充了修改意见，就基于草案 + 审核结果生成最终答复。
   - 如果不是规划类请求，则普通聊天会直接走到这里生成最终回复。

因此，这个 agent 的特点不是“一步出结果”，而是：

**用户输入 → 判断任务类型 → 必要时查工具 → 生成草案 → 等人工确认 → 输出最终结果**。

### 2.4 为什么要有 checkpoint

在 [app/agent/graph.py](app/agent/graph.py) 里，LangGraph 使用了 PostgreSQL checkpointer。

这意味着：
- 智能体工作流状态会和 `conversation_id` 绑定
- 在人工确认中断后，可以继续恢复执行
- 不需要把所有流程都塞在一次同步请求里完成

这也是它能支持“先出草案，再人工确认，再继续生成最终方案”的关键。

---

## 3. LLM 是怎么选型和路由的

模型路由在 [app/llm/router.py](app/llm/router.py)。

当前支持两类提供方：
- DeepSeek
- Qwen（通过 DashScope OpenAI 兼容接口）

路由策略大致是：
- 用户明确指定 `deepseek` 或 `qwen` 时，直接用指定模型
- 如果是 `auto`：
  - 推理、多步骤、路线规划、行程规划、ReAct 场景优先用 DeepSeek
  - 普通聊天优先用 Qwen
- 主模型失败时，自动 fallback 到另一个模型

所以这里并不是把模型写死，而是做了一层“按任务类型自动选模型”的封装。

---

## 4. 地图能力是怎么接进来的

高德地图相关能力在 [app/mcp/amap.py](app/mcp/amap.py)。

这一层做的事情是：
- 通过 `langchain-mcp-adapters` 连接高德 MCP 服务
- 对外暴露三个更业务化的能力：
  - `plan_route`：路线规划
  - `search_hotels`：查询酒店 POI
  - `search_attractions`：查询景点 POI
- 地址不是经纬度时，先尝试做地理编码
- 如果没有配置高德 key，就返回离线占位工具，避免直接崩掉

可以理解为，这一层把“底层 MCP 工具”包装成了“智能体更容易使用的业务工具层”。

---

## 5. 数据库层是怎么组织的

### 5.1 配置

配置在 [app/core/config.py](app/core/config.py)。

这里统一管理：
- 应用基础配置
- 数据库连接串
- checkpoint 数据库连接串
- DeepSeek / Qwen 配置
- 高德 MCP 配置
- 前端跨域地址
- 超时时间等

`Settings` 基于 `pydantic-settings`，默认从 `.env` 读取环境变量。

### 5.2 数据库连接

数据库 Session 和 Engine 在 [app/db/session.py](app/db/session.py)。

主要职责：
- 创建 SQLAlchemy 异步引擎
- 创建 `AsyncSession` 工厂
- 给 FastAPI 依赖注入提供 `get_session()`

### 5.3 数据模型

ORM 模型在 [app/db/models.py](app/db/models.py)。

当前核心表有三张：

1. `conversations`
   - 会话主表
   - 存标题、状态、创建时间、更新时间

2. `messages`
   - 会话消息表
   - 存 user / assistant 消息内容和 metadata

3. `human_approvals`
   - 人工确认表
   - 存草案 payload、审核状态、审核结果

它们共同组成了“一个可追踪、可中断恢复的会话系统”。

### 5.4 数据访问层

仓储层在 [app/db/repository.py](app/db/repository.py)。

这里封装了常用数据库操作，比如：
- 创建会话
- 列出会话
- 获取会话详情
- 新增消息
- 更新会话状态
- 创建审批记录
- 查找最近待处理审批
- 完成审批

这样 API 层不需要直接写 SQLAlchemy 查询逻辑，职责更清晰。

### 5.5 初始化数据库

数据库初始化逻辑在：
- [app/db/init_db.py](app/db/init_db.py)
- [scripts/init_db.py](scripts/init_db.py)

作用是：
- 创建业务表
- 初始化 LangGraph checkpoint 所需的表结构

你之前执行的 `python -m scripts.init_db`，本质上就是走这里。

---

## 6. API 层分别提供了什么

接口定义主要在 [app/api/conversations.py](app/api/conversations.py)，数据结构在 [app/api/schemas.py](app/api/schemas.py)。

目前这套后端围绕“会话”提供了几类接口：

1. **创建会话**
   - `POST /conversations`

2. **获取会话列表**
   - `GET /conversations`

3. **获取单个会话详情**
   - `GET /conversations/{conversation_id}`

4. **发送消息（普通响应）**
   - `POST /conversations/{conversation_id}/messages`

5. **发送消息（流式响应）**
   - `POST /conversations/{conversation_id}/messages/stream`
   - 通过 SSE 返回 `start / token / message / approval / done / error`

6. **提交人工审批结果**
   - `POST /conversations/{conversation_id}/approvals`

其中，流式接口是前端体验更好的主通道，因为它可以边生成边显示，同时把人工确认事件实时推给前端。

---

## 7. 各个文件夹分别是做什么的

### `app/`
后端主应用代码目录。

#### `app/api/`
API 接口层。
- `conversations.py`：会话相关接口、流式响应、审批提交
- `schemas.py`：请求体和响应体的数据模型

#### `app/agent/`
智能体编排层。
- `graph.py`：LangGraph 工作流主实现
- `prompts.py`：系统提示词、草案提示词、最终回复提示词
- `state.py`：工作流状态定义

#### `app/core/`
核心配置层。
- `config.py`：环境变量、数据库、模型、MCP 等统一配置

#### `app/db/`
数据库层。
- `models.py`：ORM 表结构
- `session.py`：数据库连接和会话工厂
- `repository.py`：数据库读写封装
- `init_db.py`：初始化业务表和 checkpoint 表

#### `app/llm/`
模型路由层。
- `router.py`：根据任务类型选择 DeepSeek / Qwen，并处理 fallback

#### `app/mcp/`
外部工具集成层。
- `amap.py`：高德地图 MCP 接入与业务封装

### `scripts/`
脚本目录。
- `init_db.py`：初始化数据库用的启动脚本

### `tests/`
测试目录。
- 当前至少包含 LLM 路由相关测试
- 后续应该继续补充 agent、API、数据库集成测试

### `.venv/`
本地 Python 虚拟环境，不属于业务代码。

---

## 8. 从架构角度怎么理解这套 backend

如果从分层角度看，可以把它理解成下面这几层：

1. **接口层**：FastAPI 接请求，对外暴露 REST + SSE
2. **编排层**：TravelAgent 用 LangGraph 组织推理流程
3. **能力层**：LLMRouter 负责模型选择，AmapMCPClient 负责地图工具能力
4. **持久化层**：SQLAlchemy + PostgreSQL 保存会话、消息、审批、checkpoint
5. **配置层**：Settings 统一管理所有运行参数

这套结构的优点是：
- API、智能体、数据库、工具接入职责分离
- 可以支持普通聊天，也可以支持有状态的旅游规划
- 可以处理中断 / 人工审批 / 恢复执行这类典型 agent 场景
- 前端既可以走普通响应，也可以走流式响应

---

## 9. 目前这套 backend 最值得关注的几个点

如果你后面要继续开发 backend，我建议优先关注这几个地方：

1. **[app/api/conversations.py](app/api/conversations.py)**
   - 这里决定前后端怎么交互
   - 包括普通消息、流式消息、审批提交的完整入口

2. **[app/agent/graph.py](app/agent/graph.py)**
   - 这里是整个智能体流程的核心
   - 任务分类、工具调用、草案生成、人工确认、最终回复都在这里

3. **[app/llm/router.py](app/llm/router.py)**
   - 这里决定不同任务走哪个模型，以及失败时怎么兜底

4. **[app/mcp/amap.py](app/mcp/amap.py)**
   - 这里决定高德工具怎么被 agent 使用

5. **[app/db/models.py](app/db/models.py)** 和 [app/db/repository.py](app/db/repository.py)
   - 这里决定数据如何存、如何查

---

## 10. 一句话总结

这个 backend 本质上是一个：

**基于 FastAPI + LangGraph + PostgreSQL + 高德 MCP 的、有会话状态、支持人工确认的广东文旅智能体服务端。**
