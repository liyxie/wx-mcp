"""MCP tool definitions and dispatch for the account manager."""

from __future__ import annotations

from typing import Any, Callable

from .accounts import AccountManager
from .errors import WeChatMCPError


def _media_type_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "enum": ["image", "file", "video"],
        "description": "媒体类型：image 图片、file 文件、video 视频",
    }


def _media_ref_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": "由 upload_media 返回的已上传媒体引用",
        "properties": {
            "encrypt_query_param": {"type": "string"},
            "aes_key": {"type": "string"},
            "encrypt_type": {"type": "integer"},
            "encrypted_file_size": {"type": "integer"},
            "raw_size": {"type": "integer"},
        },
        "required": ["encrypt_query_param", "aes_key"],
        "additionalProperties": True,
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_accounts",
        "description": "列出当前已保存/可用的微信账号及在线状态。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "login_account",
        "description": "为一个微信账号发起扫码登录。返回二维码链接，登录成功后自动保存账号并保持在线。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "本地账号标识（例如 work、personal），用于区分多个微信账号",
                },
                "force": {
                    "type": "boolean",
                    "description": "是否强制重新扫码登录（默认 false，已有登录态则直接复用）",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "get_login_status",
        "description": "查询某个账号的扫码登录状态（waiting/scaned/confirmed/expired/error 等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "本地账号标识"},
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "submit_verify_code",
        "description": "当登录需要配对码（need_verifycode）时，提交微信手机上显示的配对码。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "code": {"type": "string", "description": "微信手机上显示的配对码"},
            },
            "required": ["account_id", "code"],
        },
    },
    {
        "name": "logout_account",
        "description": "登出并清除指定微信账号的本地凭据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "send_message",
        "description": "向微信账号发送文本消息。to_user_id 留空时发给该账号绑定的微信（自己），长文本会自动分段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "本地账号标识"},
                "to_user_id": {
                    "type": "string",
                    "description": "接收人 user_id；留空则发给账号绑定的微信（自己）",
                },
                "text": {"type": "string", "description": "要发送的文本内容"},
            },
            "required": ["account_id", "text"],
        },
    },
    {
        "name": "send_media",
        "description": "向微信账号发送多媒体消息（图片/文件/视频）。file_path 或 data_base64 二选一，或直接传 upload_media 返回的 media_ref。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "media_type": _media_type_schema(),
                "to_user_id": {"type": "string", "description": "接收人 user_id；留空则发给账号绑定的微信"},
                "file_path": {"type": "string", "description": "服务器上的媒体文件路径"},
                "data_base64": {"type": "string", "description": "媒体文件内容的 base64 编码"},
                "file_name": {"type": "string", "description": "文件名（file 类型建议提供）"},
                "caption": {"type": "string", "description": "随媒体一起发送的说明文本"},
                "media_ref": _media_ref_schema(),
            },
            "required": ["account_id", "media_type"],
        },
    },
    {
        "name": "upload_media",
        "description": "将媒体文件上传到微信 CDN（只上传、不发送），返回可用于 send_media 的 media_ref。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "media_type": _media_type_schema(),
                "to_user_id": {"type": "string", "description": "接收人 user_id；留空则使用账号绑定的微信"},
                "file_path": {"type": "string", "description": "服务器上的媒体文件路径"},
                "data_base64": {"type": "string", "description": "媒体文件内容的 base64 编码"},
                "file_name": {"type": "string", "description": "文件名（file 类型建议提供）"},
            },
            "required": ["account_id", "media_type"],
        },
    },
]


class ToolRegistry:
    def __init__(self, manager: AccountManager) -> None:
        self.manager = manager
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "list_accounts": self._list_accounts,
            "login_account": self._login_account,
            "get_login_status": self._get_login_status,
            "submit_verify_code": self._submit_verify_code,
            "logout_account": self._logout_account,
            "send_message": self._send_message,
            "send_media": self._send_media,
            "upload_media": self._upload_media,
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return TOOLS

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            raise WeChatMCPError(f"Unknown tool: {name}", "UNKNOWN_TOOL")
        if not isinstance(arguments, dict):
            arguments = {}
        return handler(arguments)

    # ------------------------------------------------------------- handlers

    def _list_accounts(self, _args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.list_accounts()

    def _login_account(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.login_account(args.get("account_id"), bool(args.get("force")))

    def _get_login_status(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.get_login_status(args.get("account_id"))

    def _submit_verify_code(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.submit_verify_code(
            args.get("account_id"), str(args.get("code") or "")
        )

    def _logout_account(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.logout_account(args.get("account_id"))

    def _send_message(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.send_message(
            args.get("account_id"),
            args.get("text") or "",
            args.get("to_user_id"),
        )

    def _send_media(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.send_media(
            args.get("account_id"),
            args.get("media_type"),
            to_user_id=args.get("to_user_id"),
            file_path=args.get("file_path"),
            data_base64=args.get("data_base64"),
            file_name=args.get("file_name"),
            caption=args.get("caption"),
            media_ref=args.get("media_ref"),
        )

    def _upload_media(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.manager.upload_media(
            args.get("account_id"),
            args.get("media_type"),
            to_user_id=args.get("to_user_id"),
            file_path=args.get("file_path"),
            data_base64=args.get("data_base64"),
            file_name=args.get("file_name"),
        )
