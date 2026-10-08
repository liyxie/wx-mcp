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


class ContextRequiredError(WeChatMCPError):
    """A valid ``context_token`` is required before the bot can push a message.

    iLink rejects bot-initiated sends with ``ret=-2 errmsg="prepare failed"``
    when there is no fresh inbound message from the recipient.  This is a
    protocol requirement, not a rate limit or an account problem.
    """

    def __init__(self, user_id: str, *, stale: bool = False) -> None:
        self.user_id = user_id
        self.stale = stale
        if not user_id:
            message = (
                "No valid recipient user_id is available and the bot has no "
                "context_token. Please bind a WeChat account and have that "
                "WeChat send a message to the bot first."
            )
        else:
            message = (
                f"No usable context_token for recipient '{user_id}'. "
                "WeChat iLink only allows the bot to send after it has received "
                "an inbound message from that recipient. Please send any message "
                "to the bot from WeChat, wait a moment for the long-poll to pick "
                "it up, then retry."
            )
            if stale:
                message += (
                    " The previously cached token was rejected by the server, "
                    "so a fresh inbound message is required."
                )
        super().__init__(message, "CONTEXT_REQUIRED")


__all__ = [
    "AccountError",
    "ApiError",
    "AuthError",
    "ContextRequiredError",
    "MediaError",
    "NoContextError",
    "WeChatBotError",
    "WeChatMCPError",
]
