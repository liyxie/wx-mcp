"""Error types used by wx-mcp.

The service delegates to ``wechatbot-sdk`` and re-exports its exceptions so
callers only need to import this module for error handling.
"""

from wechatbot.errors import (
    ApiError,
    AuthError,
    MediaError,
    NoContextError,
    WeChatBotError,
)


class WeChatMCPError(WeChatBotError):
    """Base error for errors raised by the wx-mcp service itself."""


class AccountError(WeChatMCPError):
    """Account management error."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "ACCOUNT_ERROR")


__all__ = [
    "AccountError",
    "ApiError",
    "AuthError",
    "MediaError",
    "NoContextError",
    "WeChatBotError",
    "WeChatMCPError",
]
