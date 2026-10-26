# 天软差旅合规多智能体系统

基于 FastAPI + LangGraph + RAG 的企业差旅报销审核 Demo：用户在前端对话式提交报销需求，系统先由**审核 Agent** 依据公司制度与金额做合规判定，只在"审核通过且用户明确要求报销/打款"时，才交由**打款 Agent** 生成打款单，全程 SSE 流式输出。

## 功能概览

- 对话式差旅费合规审核（住宿、交通、餐饮、补贴等）
- 基于公司制度的 RAG 检索，结论有据可依，降低模型幻觉
- 审核 Agent 与打款 Agent 职责分离，避免"只是咨询是否合规"也触发打款
- 打款单号自动生成（`PAY-XXXXXX`），审批不通过不会打款
- 流式回答、Markdown 渲染、多轮会话持久化
- 前后端独立 Docker 镜像

## 系统架构

```
React SPA (Vite)
   |  POST /api/chat/stream  (SSE)
   v
FastAPI (async, Uvicorn)
   |  会话历史读写 (SQLAlchemy async + SQLite)
   v
LangGraph 编排
   |-- 审核 Agent (ReAct: DeepSeek + 工具)
   |      |-- calculator      金额计算
   |      `-- search_policy   ChromaDB 制度检索
   `-- 打款 Agent (确定性节点，生成打款单)
```

一次请求的流程：

1. 前端挂载时调用 `GET /api/session` 获取 `session_id`
2. 发送消息到 `POST /api/chat/stream`
3. 后端读取该会话历史，保存用户消息
4. 审核 Agent 流式推理并调用工具，输出审核结论
5. 若结论为"审批通过"（且不含"不予报销"），并且意图判定为"要求报销/打款"，则调用打款 Agent
6. 流结束后把完整回复写入 `messages` 表

## 技术栈

| 层次 | 技术 | 说明 |
| --- | --- | --- |
| 后端框架 | FastAPI、Uvicorn | 异步接口、`StreamingResponse` 输出 SSE |
| 多智能体编排 | LangGraph `StateGraph` | 审核与打款分别编译为独立图 |
| Agent 实现 | LangChain `create_react_agent` | 审核 Agent 的工具调用循环 |
| 模型接入 | `langchain_openai.ChatOpenAI` | OpenAI 兼容协议访问 DeepSeek |
| 向量检索 | ChromaDB、`langchain_chroma` | 本地持久化向量库 `chroma_db/` |
| 文档处理 | `TextLoader`、`RecursiveCharacterTextSplitter` | 制度文档切片（200 字，重叠 20） |
| 数据持久化 | SQLAlchemy 2.0 async、aiosqlite | `sessions`、`messages` |
| 配置管理 | python-dotenv | 从 `.env` 读取密钥 |
| 前端 | React 19、Vite 8 | 单页应用与开发服务器 |
| UI 组件 | Ant Design 6、@ant-design/icons | 侧边栏布局、输入框、加载态 |
| 前端路由 | react-router-dom 7 | "智能审查""系统架构"两个页面 |
| Markdown | react-markdown 10、remark-gfm | 渲染加粗、表格、列表 |
| 部署 | Docker 多阶段构建、Nginx | 后端 `python:3.12-slim`，前端 `node:20-alpine` + `nginx:alpine` |

## 使用的大模型

| 模型 | 供应商 | 调用地址 | 用途 | 环境变量 |
| --- | --- | --- | --- | --- |
| `deepseek-chat` | DeepSeek | `https://api.deepseek.com/v1` | 审核推理、工具调用、生成结论、打款意图判定（`temperature=0`） | `DEEPSEEK_API_KEY` |
| `embedding-2` | 智谱 AI | `https://open.bigmodel.cn/api/paas/v4/` | 制度文本向量化与检索，不生成文本 | `ZHIPU_API_KEY` |

两个 Key 缺一不可：检索器在导入 `tools.py` 时就初始化，智谱 Key 失效会导致服务无法启动；DeepSeek Key 失效则审核阶段直接报错（前端会显示异常信息）。

## 多智能体设计

### 审核 Agent

- 节点：`approval_node`
- 提示词要求必须调用工具算账与查制度，合规输出"审批通过"，违规输出"不予报销"并说明原因
- 工具：
  - `calculator`：清洗表达式后计算金额，如 `550+800`
  - `search_policy`：从 ChromaDB 检索最相关的 2 条制度条款
- 由单节点图 `review_agent` 承载，只做审核，不涉及打款

### 打款 Agent

- 节点：`payment_node`
- 不调用大模型，直接生成打款文案与 `PAY-` 开头的单号（UUID 前 6 位大写）
- 由独立图 `payment_agent` 承载

### 调度逻辑

`run_agent_stream` 负责串联：

1. 先流式运行审核图
2. 根据审核文本判断是否通过
3. 调用 `wants_payment` 判断用户意图：咨询标准、询问是否合规、问"能否报销"都判为 `REVIEW`；只有"帮我报销""发起打款""提交报销"等才判为 `PAY`；判定异常时默认 `REVIEW`
4. 仅当"通过 + PAY"时运行打款图

### 流式输出要点

- 使用 `astream_events(version="v2")` 监听 `on_chat_model_stream`，过滤 `Thought:`、`Action:` 等中间步骤
- 打款节点不产生模型分片，改为监听 `on_chain_end` 且节点名为 `payment`
- 推送前对内容做 `strip()`：内容中的 `\n\n` 是 SSE 事件分隔符，不处理会被前端截断

## RAG 知识库

- 语料：`policy.txt`，包含城市等级、住宿标准、交通标准、餐饮补贴、违规红线五章
- 首次运行时自动切片并向量化，持久化到 `./chroma_db`；之后直接加载
- 检索参数：`k=2`，召回片段拼接后交给审核 Agent
- 修改制度后需删除 `chroma_db/` 重新建库

## 接口说明

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/session` | 创建 UUID 会话并写库，返回 `session_id` |
| `POST` | `/api/chat/stream` | 入参 `{session_id, text}`，返回 `text/event-stream` |

SSE 每条消息格式为 `data: {内容}\n\n`。后端异常会以 `data: 后端处理异常：...` 返回，避免前端无限等待。

## 数据模型

- `sessions`：会话 ID（UUID）、标题、创建时间
- `messages`：自增 ID、所属会话、角色（`user`/`assistant`）、内容、时间
- 删除会话时级联删除消息
- 数据库文件 `agent.db` 位于项目根目录，已加入 `.gitignore`

## 目录结构

```
.
├── agent_core.py        # 模型初始化、多 Agent 编排、SSE 流式接口
├── main.py              # FastAPI 应用、会话与聊天接口、启动建表
├── tools.py             # calculator / search_policy 工具，ChromaDB 初始化
├── database.py          # 异步引擎、SessionLocal、Base、get_db
├── models.py            # Session / Message 模型
├── crud.py              # 会话与消息的异步 CRUD
├── policy.txt           # 差旅报销制度语料
├── requirements.txt     # Python 依赖
├── Dockerfile           # 后端镜像
├── index.html           # v1 单体演示页（遗留文件，React 版不再使用）
├── agent.db             # SQLite 数据文件（本地生成，不纳入版本管理）
└── frontend/            # React 前端
    ├── src/App.jsx      # 布局与侧边导航
    ├── src/pages/Chat.jsx   # 聊天页与 SSE 解析
    ├── src/pages/About.jsx  # 架构说明页
    ├── Dockerfile       # 前端多阶段构建 + Nginx
    └── package.json
```

## 快速开始

### 1. 配置环境变量

在项目根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_deepseek_key
ZHIPU_API_KEY=your_zhipu_key
```

### 2. 启动后端

```powershell
cd d:\agent
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

首次启动会加载/构建 `chroma_db`，需要数秒；接口文档见 `http://127.0.0.1:8000/docs`。

### 3. 启动前端

```powershell
cd d:\agent\frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。前端请求地址固定为 `http://127.0.0.1:8000`。

### 4. Docker（可选）

```powershell
# 后端
docker build -t tianruan-agent .
docker run --env-file .env -p 8000:8000 tianruan-agent

# 前端
cd frontend
docker build -t tianruan-frontend .
docker run -p 3000:80 tianruan-frontend
```

说明：`docker-compose.yml` 已移除，需要编排时可按上述两个服务自行补回；容器内未挂载卷，重建后 `agent.db` 数据会丢失。

## 示例

| 输入 | 预期行为 |
| --- | --- |
| 帮我审核一下，普通员工一线城市住宿 1 晚 500 元是否合规？ | 只输出审核结论，不出现打款信息 |
| 住宿标准是多少？ | 返回制度条款，不打款 |
| 普通员工一线城市住宿 1 晚 2000 元，帮我报销 | 说明超标部分自理、不予报销，不打款 |
| 普通员工一线城市住宿 1 晚 500 元，帮我报销 | 审核通过后输出 `PAY-` 打款单 |

## 已知限制与改进方向

1. 无鉴权与限流，CORS 为 `*`，仅适合内网演示
2. `get_history` 返回全部历史，长会话会增大 token 消耗（注释中的"最近 10 轮"未实现）
3. 打款为模拟流程，未对接支付系统，无审批流、幂等与台账
4. `wants_payment` 额外调用一次大模型，增加约 1 秒首字延迟
5. SSE 解析较简化：模型分片若含 `\n\n` 会丢失空行，规范做法是按 SSE 多行 `data:` 编码
6. 前端后端地址硬编码，建议改为环境变量或 Nginx 反向代理
7. 检索粒度较粗（200 字切片、`k=2`），制度更新需重建向量库
8. 缺少自动化测试与 CI

## 版本记录

- v2.0：前端重构为 React + Ant Design + Vite，接入 ChromaDB 真 RAG 与 LangGraph 多智能体，优化 SSE 流式输出
- v2.1：新增 SQLite 会话持久化与 Docker 镜像；补全流式异常提示
- v2.2：拆分审核 Agent 与打款 Agent，新增打款意图判定，修复打款内容被 SSE 分隔符截断的问题
