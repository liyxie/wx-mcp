# wx-mcp

基于 `wechatbot-sdk` 实现的微信消息推送 MCP 服务，帮助 Agent 系统接入微信消息推送。

## 功能

- **本地 / 远程连接**：同时支持 MCP 的 `stdio`（本地）与 streamable HTTP（远程）传输。
- **保持登录**：启动后为每个已保存账号运行后台长轮询，维持微信登录态。
- **多账号管理**：每个账号一个独立的 `WeChatBot` 实例、独立事件循环与凭据目录。
- **对外工具**：
  - 获取当前可用微信账号及在线状态
  - 向微信账号发送文本 / 多媒体消息（图片、文件、视频）
  - 媒体文件上传到微信 CDN

## 依赖与安装

项目使用仓库内 `wechatbot/python` 下的 `wechatbot-sdk`（源码也可直接查看
`../wechatbot`）。虚拟环境已创建为 `wx-mcp\.venv`：

```powershell
cd E:\MyWenJian\learn\wx-mcp

# 安装 SDK（本项目已安装，供首次复现使用）
.\.venv\Scripts\python.exe -m pip install "..\wechatbot\python"

# 安装开发依赖（可选，运行测试用）
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 目录结构

```text
wx-mcp/
├── docs/初步设计.md      # 需求文档
├── wx_mcp/
│   ├── __main__.py       # 命令行入口
│   ├── mcp_server.py     # MCP JSON-RPC（stdio + HTTP）
│   ├── tools.py          # 工具定义与分发
│   ├── accounts.py       # 多账号管理
│   ├── runtime.py        # 单账号运行时（WeChatBot + asyncio loop）
│   └── errors.py         # SDK 异常重导出 + 服务自有异常
├── tests/
├── requirements.txt
└── README.md
```

## 启动

### HTTP（远程连接，默认）

```powershell
cd E:\MyWenJian\learn\wx-mcp
.\.venv\Scripts\python.exe -m wx_mcp --transport http --host 127.0.0.1 --port 18080
```

监听 `http://127.0.0.1:18080`，MCP streamable HTTP 端点接受 `POST /` 或
`POST /mcp` 的 JSON-RPC 请求。需要被其他机器访问时把 `--host` 改为 `0.0.0.0`。

### stdio（本地连接）

```powershell
cd E:\MyWenJian\learn\wx-mcp
.\.venv\Scripts\python.exe -m wx_mcp --transport stdio
```

适合配置到 Claude Desktop / VS Code 等本地 MCP 客户端。

## 客户端配置示例

远程 HTTP：

```json
{
  "mcpServers": {
    "wx-mcp": {
      "type": "http",
      "url": "http://127.0.0.1:18080/mcp"
    }
  }
}
```

本地 stdio：

```json
{
  "mcpServers": {
    "wx-mcp": {
      "command": "E:/MyWenJian/learn/wx-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "wx_mcp", "--transport", "stdio"],
      "cwd": "E:/MyWenJian/learn/wx-mcp"
    }
  }
}
```

## 使用流程

1. 调用 `login_account`，传入一个本地账号标识（如 `work`），获得二维码链接。
2. 用微信扫码，重复调用 `get_login_status` 直到 `status` 变为 `confirmed`。
3. 之后即可用 `send_message` / `send_media` 推送消息。

如果登录过程中返回 `need_verifycode`，把微信手机上显示的配对码通过
`submit_verify_code` 提交即可。

## 工具说明

| 工具 | 说明 |
| --- | --- |
| `list_accounts` | 列出已保存账号、登录态、在线状态 |
| `login_account` | 发起扫码登录（返回二维码 URL） |
| `get_login_status` | 查询扫码登录进度 |
| `submit_verify_code` | 提交登录配对码 |
| `logout_account` | 登出并清除本地凭据 |
| `send_message` | 发送文本消息（自动分段） |
| `send_media` | 发送图片 / 文件 / 视频 |
| `upload_media` | 只上传媒体到 CDN，返回 media_ref |

### 发送目标（to_user_id）

- 不传 `to_user_id`：推送给该账号绑定的微信（自己），走“推送模式”，无需
  `context_token`。因为 `wechatbot-sdk` 的 `WeChatBot.send` 要求缓存过
  `context_token`，所以推送模式通过 SDK 的 `ILinkApi` 直接构造并发送消息。
- 传 `to_user_id`：需要该联系人最近给 bot 发过消息，服务会自动使用长轮询缓存
  的 `context_token` 回复；否则返回 `NO_CONTEXT` 错误。

### 多媒体

`send_media` / `upload_media` 的 `media_type` 支持 `image`、`file`、`video`。
内容通过 `file_path`（服务器本地路径）或 `data_base64` 二选一提供。也可以先调用
`upload_media` 得到 `media_ref`，再把它传给 `send_media`，避免重复上传。
上传使用 SDK 的 `WeChatBot.upload`。

## 账号数据

默认保存在 `wx-mcp/data/accounts/<account_id>/`：

```text
data/accounts/<account_id>/
└── credentials.json      # token / accountId(bot_id) / userId
```

可通过 `WX_MCP_DATA_DIR` 或 `--data-dir` 修改。

## 环境变量

见 [.env.example](.env.example)。常用项：

- `WX_MCP_TRANSPORT`：`http` 或 `stdio`
- `WX_MCP_HOST` / `WX_MCP_PORT`：HTTP 监听地址
- `WX_MCP_DATA_DIR`：账号数据目录
- `WX_MCP_BASE_URL`：iLink API 地址
- `WX_MCP_BOT_AGENT`：发送到 `base_info` 的 UA 风格标识

## 测试

```powershell
cd E:\MyWenJian\learn\wx-mcp
.\.venv\Scripts\python.exe -m pytest
```

说明：真实的扫码登录、发消息与媒体上传需要可访问 `ilinkai.weixin.qq.com`
的网络环境，并需要用户在微信端扫码确认，无法在纯本地自动化测试中覆盖。
