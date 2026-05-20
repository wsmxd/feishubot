# MA-Agent

一个专注于飞书生态的 Python Bot 项目，支持多轮对话、工具调用、图片分析和 MCP 外部工具接入。

## 项目结构

```text
feishubot/
├── src/feishubot/
│   ├── app.py            # FastAPI 应用
│   ├── ai/
│   │   ├── core/         # 通用 schema / registry / error
│   │   ├── providers/    # 模型适配器（openai_compatible / echo）
│   │   ├── tools/        # 内置工具（terminal / calculator / web_search / soul_memory / save_image）
│   │   ├── mcp/          # MCP 客户端（连接外部 MCP 服务器）
│   │   ├── orchestrator/ # Agent 执行编排层
│   │   ├── prompts/      # Prompt 模板
│   │   ├── memory/       # 会话状态与记忆管理
│   │   └── configs/      # 路由与工具配置样例
│   ├── config.py         # 环境配置（pydantic-settings）
│   ├── channel/          # 消息通道抽象层（feishu）
│   ├── feishu.py         # 飞书 API 客户端（lark-oapi SDK）
│   └── cli.py            # CLI 入口（chat / gateway / events / setup）
├── mcp_servers.default.toml  # MCP 服务器配置模板
├── tools.default.toml        # 内置工具运行配置
├── models.toml               # 多模型定义
├── .env                      # 环境变量
└── pyproject.toml
```

## 快速开始

### 一键运行（推荐）

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/wsmxd/feishubot/main/scripts/bootstrap.sh)
```

### 本地开发

1. 创建并激活虚拟环境（Python >= 3.11）：

```bash
uv venv && source .venv/bin/activate
```

2. 安装依赖：

```bash
uv sync
```

3. 交互式配置：

```bash
feishubot setup
```

4. 启动终端对话：

```bash
feishubot chat
```

或启动 HTTP 网关：

```bash
feishubot gateway --host 0.0.0.0 --port 8000
```

### 环境文件

- 默认路径：`~/.feishubot/.env`
- 若当前目录存在 `.env`，优先读取（便于本地开发）
- 可通过 `FEISHUBOT_ENV_FILE` 显式指定

## 大模型配置

### 单模型

在 `.env` 中配置：

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://dashscope.aliyuncs.com
LLM_API_KEY=<你的密钥>
LLM_MODEL=qwen-plus
LLM_CHAT_PATH=/compatible-mode/v1/chat/completions
```

### 多模型（推荐）

```bash
LLM_ACTIVE_MODEL=qwen
LLM_MODELS_CONFIG_PATH=models.toml
```

切换模型只需修改 `LLM_ACTIVE_MODEL` 并重启。内置预设：`qwen`、`kimi`、`deepseek`、`glm`。

### HTTP 接口测试

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "user_id": "demo-user"}'
```

## 工具系统

### 内置工具

| 工具 | 说明 |
|---|---|
| `terminal` | 执行 shell 命令（sync / async / cancel） |
| `calculator` | 数学运算 |
| `web_search` | 网络搜索 |
| `soul_memory` | 用户画像持久化（写入 SOUL.md） |
| `save_image` | 将图片保存到本地文件，返回路径供 MCP 服务使用 |

工具配置文件 `tools.default.toml` 支持 `enabled_tools`、`routing` 超时、`terminal.blocked_commands`。

### MCP 外部工具接入

通过 `mcp_servers.toml` 配置外部 MCP 服务器，启动时自动发现工具并注册到 Agent 工具表：

```toml
[mcp_servers.filesystem]
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

[mcp_servers.remote_api]
transport = "streamable_http"
url = "http://localhost:8000/mcp"
```

配置路径通过 `MCP_SERVERS_CONFIG_PATH` 环境变量指定，默认查找项目根目录 `mcp_servers.toml`。

## 图片分析

飞书用户发送图片时，Bot 自动：
1. 下载图片并保存到本地（默认 `~/.feishubot/images/`，最多 30 张，超出自动淘汰最老）
2. 转为 base64 data URL 发送视觉模型分析
3. 将分析结果和本地路径存入会话记忆

本地路径可在 MCP 工具调用中作为参数使用。

## 飞书接入

### 长连接模式（推荐）

```bash
feishubot events --log-level INFO
```

无需公网地址，长连接失败时自动 fallback 到 webhook 网关。

### Webhook 模式

```bash
feishubot gateway --host 0.0.0.0 --port 8000
```

需公网地址（Cloudflare Tunnel / ngrok），事件地址设为 `https://<your-domain>/webhook/feishu/events`。

### 飞书配置项

- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`（必需）
- `FEISHU_VERIFICATION_TOKEN` / `FEISHU_ENCRYPT_KEY`（可选）
- `GATEWAY_INTERNAL_API_KEY`（可选，保护内部推送 API）

## License

Apache-2.0，详见 `LICENSE`。