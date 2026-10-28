# 天软差旅合规多智能体系统

基于 FastAPI + React + LangGraph + ChromaDB + DeepSeek 的差旅报销审核 Demo。用户用自然语言描述行程与费用，系统依次完成**信息抽取 → 必填校验 → 审核 Agent 核算 → 打款 Agent 出单**，全程 SSE 流式输出；缺失信息自动追问，核算合规后生成 `PAY-XXXXXX` 打款单。

## 功能概览

- 用户名密码登录（bcrypt 存储密码）+ JWT 鉴权，会话按用户隔离
- 对话式差旅费核算（交通、住宿、打车、补助）
- 结构化信息抽取：城市、职级、住宿总额/晚数、打车费、车次、发车时间、返程时间
- 必填项校验，缺字段直接追问，不进入核算
- 审核 Agent 工具核算：制度语义检索、差旅补助、火车票降级、联网查车次
- 制度知识库 RAG：ChromaDB + 智谱 `embedding-2`，不可用时自动降级为关键词检索
- LangGraph 状态图编排，审核通过后需用户明确回复“确认打款”才进入打款节点
- 会话列表 / 切换 / 删除，历史消息自动裁剪后送入模型
- 登录与对话接口限流、CORS 白名单、401 自动跳转登录
- 流式输出可手动停止（AbortController），刷新后历史消息还原
- 后端 pytest 测试 + GitHub Actions CI
- 前后端独立 Docker 镜像，SQLite 与向量库数据卷持久化

## 系统架构

```
React SPA (Vite + Ant Design)
   |  JWT Bearer  /api/chat/stream (SSE, JSON 帧)
   v
FastAPI (async, Uvicorn)
   |-- 鉴权 / 限流 / CORS 白名单
   |-- 会话与消息 CRUD（SQLAlchemy async + SQLite）
   v
LangGraph StateGraph
   |-- extract    DeepSeek 抽取报销表单 JSON
   |-- validate   校验必填项，缺失则进入 ask_more 结束
   |-- audit      审核 Agent（ReAct + 工具）逐项核算
   |-- confirm    核算合规但用户未要求打款时，仅提示确认
   `-- payment    用户明确要求打款时生成打款单 PAY-XXXXXX
          |
          `-- 工具：search_policy / calculate_allowance
                   train_downgrade / search_train_info
                        |
                        `-- ChromaDB 制度向量库（智谱 embedding-2）
                            失败 -> 关键词检索降级
```

一次请求的流程：

1. 前端登录后进入主界面，拉取会话列表并加载当前会话历史
2. 发送消息到 `POST /api/chat/stream`（携带 JWT）
3. 后端校验会话归属与限流，读取裁剪后的历史，保存用户消息
4. 状态图依次执行抽取、校验；字段齐全进入审核 Agent，否则返回追问清单
5. 审核结果含“总计报销”时：若用户明确表达打款意愿（如“确认打款”）则流转到打款节点；否则只提示金额待确认，不生成打款单
6. 结果逐字以 SSE 推送；结束后把完整回复与 `PAY-` 单号落库

## 技术栈

| 层次 | 技术 | 说明 |
| --- | --- | --- |
| 后端框架 | FastAPI、Uvicorn | 异步接口、`StreamingResponse` 输出 SSE |
| 编排方式 | LangGraph `StateGraph` | 抽取 → 校验 → 审核 → 打款的条件分支 |
| Agent 实现 | LangGraph `create_react_agent` | 审核阶段的工具调用循环 |
| 模型接入 | `langchain_openai.ChatOpenAI` | OpenAI 兼容协议访问 DeepSeek |
| 向量检索 | ChromaDB、智谱 `embedding-2` | 制度片段向量化与语义检索 |
| 联网搜索 | Tavily（`langchain_community`） | 查询车次时刻与票价 |
| 数据持久化 | SQLAlchemy 2.0 async、aiosqlite | `users`、`sessions`、`messages`、`payment_records` |
| 鉴权 | bcrypt + 自实现 HS256 JWT | 无额外 JWT 依赖，密钥来自环境变量 |
| 前端 | React 19、Vite 8 | 单页应用与开发服务器 |
| UI 组件 | Ant Design 6、@ant-design/icons | 登录页、侧边会话列表、聊天界面 |
| 前端路由 | react-router-dom 7 | 登录页 / 智能审查 / 系统架构 |
| Markdown | react-markdown 10、remark-gfm | 渲染加粗、表格、列表 |
| 测试与 CI | pytest、GitHub Actions | `backend/tests`，推送自动运行 |
| 部署 | Docker 多阶段构建、Nginx | 前端 Nginx 反向代理 `/api`，SSE 不缓冲 |

## 模型与外部服务

| 名称 | 供应商 | 用途 | 环境变量 |
| --- | --- | --- | --- |
| `deepseek-chat` | DeepSeek | 信息抽取、工具调用、费用核算（`temperature=0`） | `DEEPSEEK_API_KEY` |
| `embedding-2` | 智谱 AI | 制度片段与查询向量化 | `ZHIPU_API_KEY` |
| Tavily Search | Tavily | 查询车次时刻表与二等座票价 | `TAVILY_API_KEY` |

- `DEEPSEEK_API_KEY` 缺失会导致抽取与核算失败
- `ZHIPU_API_KEY` 缺失或不可用时，RAG 自动降级为关键词检索，不影响主流程
- `TAVILY_API_KEY` 缺失时 `search_train_info` 返回提示，其余流程正常

## 工具说明

| 工具 | 入参 | 说明 |
| --- | --- | --- |
| `search_policy` | `query` | 在制度向量库中检索最相关的 4 个条款片段 |
| `calculate_allowance` | `depart_time_str`、`return_time_str` | 每天 150 元，12 点为界，去程下午算半天、返程上午算半天 |
| `train_downgrade` | `seat_class`、`actual_price`、`second_class_price` | 一等座按二等座价格报销，差价自理 |
| `search_train_info` | `depart_city`、`arrive_city`、`train_no` | Tavily 联网搜索车次信息 |

## 鉴权与稳定性

- 密码使用 bcrypt 哈希存储，JWT 有效期默认 1440 分钟
- 登录/注册按 IP 限流（默认 10 次/分钟），对话按用户限流（默认 20 次/分钟）
- CORS 仅允许配置中的来源（默认 `localhost:5173`）
- 会话、消息、删除接口均校验 `session_id` 与当前用户归属，越权返回 404
- 历史消息默认只取最近 12 条、总字符不超过 6000，单条超长内容截断
- SSE 事件统一为 `data: {"text": "..."}\n\n`；整体超时 180 秒
- 前端 401 自动清理凭证并跳转登录；支持停止生成，切换会话会中止当前请求
- RAG 构建/查询失败自动降级，5 分钟后重试；启动时后台预热向量库

## 接口说明

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | 否 | 注册并返回 JWT |
| `POST` | `/api/auth/login` | 否 | 登录并返回 JWT |
| `GET` | `/api/auth/me` | 是 | 当前用户信息 |
| `POST` | `/api/session` | 是 | 新建会话，返回 `session_id` |
| `GET` | `/api/sessions` | 是 | 当前用户会话列表 |
| `GET` | `/api/sessions/{id}/messages` | 是 | 会话历史消息 |
| `DELETE` | `/api/sessions/{id}` | 是 | 删除会话及其消息、打款记录 |
| `POST` | `/api/chat/stream` | 是 | `{session_id, text}`，返回 `text/event-stream` |

接口文档：`http://127.0.0.1:8000/docs`。

## 数据模型

- `users`：用户名（唯一）、bcrypt 密码哈希、创建时间
- `sessions`：会话 ID（UUID）、所属用户、标题、创建/更新时间
- `messages`：自增 ID、所属会话、角色（`user`/`assistant`）、内容、时间
- `payment_records`：打款单号（`PAY-` 开头，唯一）、所属会话、状态、时间
- 删除会话时同步删除消息与打款记录
- 默认数据库文件 `backend/agent.db`，Docker 中位于 `/app/data/agent.db`

## 目录结构

```
Tiansoft-Agent-Project/
├── backend/
│   ├── main.py              # 应用入口、鉴权/会话/聊天接口
│   ├── agent_core.py        # LangGraph 状态图、节点、SSE 流式输出
│   ├── tools.py             # 制度检索、补助、降级、车次搜索工具
│   ├── rag.py               # ChromaDB 向量库 + 关键词降级
│   ├── auth.py              # bcrypt 密码、HS256 JWT、当前用户依赖
│   ├── rate_limit.py        # 内存滑动窗口限流
│   ├── database.py          # 异步引擎、会话工厂、Base
│   ├── models.py            # User / Session / Message / PaymentRecord
│   ├── crud.py              # 异步 CRUD 与历史裁剪
│   ├── policy.txt           # 差旅报销制度语料
│   ├── tests/               # pytest 用例
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/api.js           # API 基址、JWT 注入、401 处理
│   ├── src/App.jsx          # 布局、会话列表、登录守卫
│   ├── src/pages/Login.jsx  # 登录/注册页
│   ├── src/pages/Chat.jsx   # 聊天页、SSE 解析、停止生成
│   ├── src/pages/About.jsx  # 架构说明页
│   ├── nginx.conf           # SPA 回退 + /api 反向代理（SSE 不缓冲）
│   └── Dockerfile
├── .github/workflows/backend-tests.yml
├── docker-compose.yml
└── README.md
```

## 快速开始

### 1. 配置环境变量

在 `backend` 目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_deepseek_key
ZHIPU_API_KEY=your_zhipu_key
TAVILY_API_KEY=your_tavily_key

JWT_SECRET=please-change-me
TOKEN_TTL_MINUTES=1440
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost

CHAT_RATE_LIMIT=20
AUTH_RATE_LIMIT=10
HISTORY_LIMIT=12
HISTORY_MAX_CHARS=6000
EMBED_MODEL=embedding-2
```

可选：`DATABASE_URL`（默认 `sqlite+aiosqlite:///./agent.db`）、`CHROMA_DIR`（默认 `backend/chroma_db`）、`RAG_WARMUP=0` 关闭启动预热。

### 2. 启动后端

```powershell
cd d:\Tiansoft-Agent-Project\backend
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### 3. 启动前端

```powershell
cd d:\Tiansoft-Agent-Project\frontend
npm install
npm run dev
```

访问 `http://localhost:5173`，首次使用在登录页切到“注册”创建账号。
前端默认请求 `http://127.0.0.1:8000`，可用 `VITE_API_BASE_URL` 覆盖；设置为空字符串时走同源（供 Docker/Nginx 代理）。

### 4. 测试

```powershell
cd d:\Tiansoft-Agent-Project\backend
python -m pytest -q
```

测试使用独立 `test_agent.db`，不调用外部模型；CI 配置见 `.github/workflows/backend-tests.yml`。

### 5. Docker（可选）

```powershell
cd d:\Tiansoft-Agent-Project
docker compose up -d --build
```

访问 `http://localhost`。`backend` 使用具名卷 `backend_data`（SQLite）与 `chroma_data`（向量库）持久化；前端 Nginx 将 `/api` 反向代理到后端。

## 示例

| 输入 | 预期行为 |
| --- | --- |
| 我29日坐C2202去北京，住宿两晚630元，打车75元，帮我算算 | 缺少“职级”，返回追问文案，不核算、不打款 |
| 我是普通员工，10月29日08:00坐C2202一等座去北京，住宿两晚630元，打车75元，10月30日14:00返程 | 输出费用明细与总计报销，提示“尚未打款”，不生成打款单 |
| 接着回复“确认打款” | 重新核算并生成 `PAY-` 打款单 |
| 住宿标准是多少？ | 缺少必填信息，返回追问清单 |

## 已知限制

1. 打款为模拟流程，未对接真实支付系统，无审批流与台账（按要求不实现）
2. 未提供线上部署与域名/HTTPS 配置（按要求不实现）
3. 限流为单进程内存实现，多副本部署需改用 Redis
4. 逐字推送会产生较多细小 SSE 事件，不支持断点续传
5. 信息抽取依赖大模型，仍可能漏抽字段

## 版本记录

- v4.1：打款改为显式授权——核算完成后只提示金额，用户回复“确认打款”等明确指令才生成打款单，避免擅自打款
- v4.0（当前版本）：新增 JWT 鉴权与限流、ChromaDB RAG、LangGraph 审核/打款状态图、会话管理与历史裁剪、前端登录页与会话列表、停止生成、Docker 数据持久化、pytest 与 CI
- v3.0：修复 SSE 帧缺少结束符导致的回复卡住问题，改为 JSON 编码事件；超时放宽至 180 秒
- v2.1：新增 SQLite 会话持久化与 Docker 镜像；补全流式异常提示
- v2.0：前端重构为 React + Ant Design + Vite，接入工具调用与流式输出
