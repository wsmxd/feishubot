# FeishuBot

一个专注于飞书生态的 Python Bot 项目骨架，建议按「先终端、后飞书」顺序推进：

- 先在终端完成多轮对话验证
- 可直接调用大模型接口（`/api/llm/chat`）
- 内置 OpenAI 兼容协议客户端（也可切回 `echo`）
- 飞书 webhook 保留为后续对接能力

## 1. 项目结构

```text
feishubot/
├── src/feishubot/
│   ├── app.py            # FastAPI 应用
│   ├── ai/               # 模型与工具调用骨架目录
│   │   ├── core/         # 通用 schema / registry / error
│   │   ├── providers/    # 各模型适配器（openai/anthropic/gemini...）
│   │   ├── tools/        # 工具定义与实现
│   │   ├── orchestrator/ # Agent 执行编排层
│   │   ├── prompts/      # Prompt 模板
│   │   ├── memory/       # 会话状态抽象
│   │   └── configs/      # 路由与工具配置样例
│   ├── config.py         # 环境配置
│   ├── feishu.py         # 飞书 API 客户端（官方 lark-oapi SDK）
│   ├── llm_client.py     # 大模型抽象与 OpenAI 兼容客户端
│   └── main.py           # 启动入口
├── .env.example
├── pyproject.toml
└── README.md
```

## 2. 快速开始

一键下载并运行（推荐）：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/wsmxd/feishubot/main/scripts/bootstrap.sh)
```

可选参数：

```bash
# 下载后仅初始化，不自动启动
bash <(curl -fsSL https://raw.githubusercontent.com/wsmxd/feishubot/main/scripts/bootstrap.sh) -- --run none

# 启动 HTTP 网关
bash <(curl -fsSL https://raw.githubusercontent.com/wsmxd/feishubot/main/scripts/bootstrap.sh) -- --run gateway
```

1. 创建并激活虚拟环境
2. 安装uv依赖：

```bash
pipx install uv
```

3. 开启虚拟环境(python版本3.14)：

```bash
uv venv --python 3.14
```

macOS / Linux：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```bash
.venv\Scripts\Activate.ps1
```

4. 安装项目依赖：

```bash
uv sync
```

5. 启动网关服务：

```bash
feishubot gateway --reload --host 0.0.0.0 --port 8000
```

6. 快速配置（推荐首次执行）：

```bash
feishubot setup
```

会进入交互式向导，快速选择 LLM 提供商（`echo` / `openai_compatible`）并写入 `.env`。
当前内置大模型预设：`qwen`、`kimi`、`deepseek`。
该向导会写入 `LLM_MODELS_CONFIG_PATH` 和 `LLM_ACTIVE_MODEL`，用于维护多个模型并快速切换。

说明：

- `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 建议在 setup 时填写（长连接必需）
- `FEISHU_VERIFICATION_TOKEN`、`FEISHU_ENCRYPT_KEY` 为可选字段（开发阶段可留空）

## 3. 先在终端跑通对话

配置好 `.env` 后可直接进入终端对话：

```bash
feishubot chat
```

可选参数：

```bash
feishubot chat --user-id demo-user --system-prompt "你是一个简洁的助手"
```

兼容旧命令（仍可用）：

```bash
feishubot-chat --user-id demo-user
```

退出方式：输入 `exit` / `quit` / `/exit`，或按 `Ctrl+C`。

工具层配置（可选）：

- 默认读取 `tools.default.toml`（仓库根目录，真实运行配置）
- 通过 `AI_TOOLS_CONFIG_PATH` 覆盖配置文件路径（可参考 `src/feishubot/ai/configs/tools.example.toml`）
- 支持 `enabled_tools` 控制可用工具集合
- `soul_memory` 默认启用，模型会在识别到稳定用户画像信息时写入 `SOUL.md`
- 支持 `routing.<tool>.timeout_seconds` 覆盖工具默认超时
- 支持 `terminal.blocked_commands` 定义禁用命令片段（命中即拒绝执行）

## 4. 再调通 HTTP 大模型接口

1. 在 `.env` 中配置（单模型或多模型二选一）：

- `LLM_PROVIDER=openai_compatible`
- `LLM_BASE_URL=https://api.openai.com`（或你的网关地址）
- `LLM_API_KEY=<你的密钥>`
- `LLM_MODEL=<你的模型名>`

多模型模式（推荐）：

- `LLM_ACTIVE_MODEL=qwen`
- `LLM_MODELS_CONFIG_PATH=src/feishubot/ai/configs/model_routes.example.toml`

切换模型时只需修改 `LLM_ACTIVE_MODEL`，然后重启 `feishubot chat` 或 gateway 进程。

2. 调用接口测试：

```bash
curl -X POST http://127.0.0.1:8000/api/llm/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好，给我一段简短的项目启动建议",
    "user_id": "demo-user"
  }'
```

也支持更适合 curl 的统一入口：

```bash
curl "http://127.0.0.1:8000/api/chat?message=你好&user_id=demo-user"
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "message=你好，给我一个简短回复"
```

`/api/chat` 和 `/api/llm/chat` 现在是同一个网关能力的两个别名，后续飞书侧转发时可以直接复用这套请求格式。

核心人格文件运行时路径默认为 `~/.feishubot/SOUL.md`（可通过 `SOUL_PROMPT_PATH` 覆盖）；`src/feishubot/ai/prompts/system/SOUL.md` 仅作为初始模板。后续如果需要更新用户姓名、称呼、习惯或爱好，可通过 `soul_memory` 工具或 `save_soul_prompt()` 写回运行时文件。

## 5. 飞书侧配置（后续）

- 在飞书开发者后台创建应用并开启机器人能力
- 先把本地网关暴露为公网地址（任选一种）

```bash
# 方案 A: Cloudflare Tunnel（推荐稳定）
cloudflared tunnel --url http://127.0.0.1:8000

# 方案 B: ngrok
ngrok http 8000
```

- 拿到公网 URL 后，设置事件订阅请求地址为：`https://<your-domain>/webhook/feishu/events`
- 建议先在飞书后台点一次「发送测试事件」，确认网关可达
- 在 `.env` 中填写：
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
  - `FEISHU_VERIFICATION_TOKEN`（可选，按你启用方式）
  - `FEISHU_ENCRYPT_KEY`（可选）
  - `GATEWAY_INTERNAL_API_KEY`（可选，配置后 `/api/feishu/push` 与 `/api/feishu/relay` 需携带 `x-api-key`）

### 5.1 内部主动推送 API（可选）

除了飞书事件回调链路，也支持内部服务主动调用 API 向飞书发消息。

1) 直接推送文本到飞书：

```bash
curl -X POST http://127.0.0.1:8000/api/feishu/push \
  -H "Content-Type: application/json" \
  -H "x-api-key: <GATEWAY_INTERNAL_API_KEY>" \
  -d '{
    "receive_id": "oc_xxx",
    "receive_id_type": "open_id",
    "text": "来自内部系统的通知"
  }'
```

2) 先调用 LLM 再把回复推送到飞书：

```bash
curl -X POST http://127.0.0.1:8000/api/feishu/relay \
  -H "Content-Type: application/json" \
  -H "x-api-key: <GATEWAY_INTERNAL_API_KEY>" \
  -d '{
    "message": "请用一句话总结今天待办",
    "receive_id": "oc_xxx",
    "receive_id_type": "open_id",
    "user_id": "internal-service"
  }'
```

`receive_id_type` 常见值：`open_id`（用户）、`chat_id`（群聊）。

### 5.2 事件处理模式

项目已接入飞书官方 `lark-oapi` SDK 事件分发器，支持两种订阅模式：

默认策略：优先使用官方 SDK 长连接；当长连接不可用或建连失败时，自动 fallback 到 webhook 网关模式。

1) 长连接模式（推荐开发调试）

```bash
feishubot events --log-level INFO
```

- 对应飞书后台订阅方式：**使用长连接接收事件**
- 无需公网回调地址
- 若长连接失败，会自动启动 webhook 网关（默认 `0.0.0.0:8000`）

可选参数：

```bash
# 调整 fallback 网关端口
feishubot events --fallback-port 9000

# 禁用 fallback（长连接失败时直接报错退出）
feishubot events --no-fallback-webhook
```

2) 开发者服务器模式（Webhook）

```bash
feishubot gateway --host 0.0.0.0 --port 8000
```

- 对应飞书后台订阅方式：**将事件发送至开发者服务器**
- 事件地址使用：`https://<your-domain>/webhook/feishu/events`

说明：

- 已注册 `im.message.receive_v1` 事件处理。
- 回调处理逻辑会快速应答，再异步调用 LLM 并发送回复，避免超过 3 秒导致重推。

### 5.3 常见问题

1) 报错：`FEISHU_APP_ID and FEISHU_APP_SECRET are required for long connection mode.`

- 原因：长连接模式必须有应用凭证
- 处理：在 `.env` 中填写 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 后重启

2) 报错：`connecting through a SOCKS proxy requires python-socks`

- 原因：当前网络走了 SOCKS 代理，WebSocket 缺少代理依赖
- 处理：执行 `uv add python-socks`，然后重启 `feishubot events`

3) 启动命令找不到：`feishubot: command not found`

- 处理 A：先激活虚拟环境再执行命令
- 处理 B：使用 `uv run feishubot events --log-level INFO`

## 6. 接入大模型说明

当前在 `llm_client.py` 提供了：

- `LLMClient` 抽象接口
- `EchoLLMClient`（本地调试）
- `OpenAICompatibleLLMClient`（兼容 OpenAI Chat Completions 协议）

保留统一接口，方便后续扩展「工具调用」「多 Agent」「任务执行器」。

## 7. 下一步建议

- 增加飞书消息去重（基于 `event_id`）
- 增加签名校验与加解密
- 增加指令路由（如 `/plan`、`/run`）
- 持久化会话上下文（Redis / PostgreSQL）

## 8. License

本项目使用 Apache-2.0 许可证，详见 `LICENSE`。

## 9. CI 与 PR 合并策略

项目已提供 GitHub Actions 工作流：

- `.github/workflows/ci.yml`：在 PR 和 `main` push 时自动执行 Ruff 格式检查、Ruff lint/安全规则检查、语法检查、基础导入检查、测试（若存在 `tests/`）
- `.github/CODEOWNERS`：指定代码所有者审阅（默认 `@wsmxd`）

