"""Command-line entry point for wx-mcp."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from wechatbot.protocol import DEFAULT_BASE_URL

from .accounts import AccountManager
from .mcp_server import McpServer, run_http, run_stdio
from .tools import ToolRegistry


def _default_data_dir() -> Path:
    env = os.environ.get("WX_MCP_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WeChat message push MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("WX_MCP_TRANSPORT", "http"),
        help="MCP transport (default: http)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("WX_MCP_HOST", "127.0.0.1"),
        help="HTTP listen host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WX_MCP_PORT", "18080")),
        help="HTTP listen port (default: 18080)",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_default_data_dir()),
        help="Directory used to persist accounts (default: wx-mcp/data)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("WX_MCP_BASE_URL", DEFAULT_BASE_URL),
        help="iLink API base URL",
    )
    parser.add_argument(
        "--bot-agent",
        default=os.environ.get("WX_MCP_BOT_AGENT"),
        help="UA-style bot_agent string sent in base_info",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    manager = AccountManager(
        args.data_dir,
        base_url=args.base_url,
        bot_agent=args.bot_agent,
    )
    # Resume persisted accounts and keep their sessions alive in the background.
    manager.start_all()

    registry = ToolRegistry(manager)
    server = McpServer(registry)

    try:
        if args.transport == "stdio":
            run_stdio(server)
        else:
            run_http(
                server,
                args.host,
                args.port,
                upload_handler=manager.upload_media_bytes,
            )
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
