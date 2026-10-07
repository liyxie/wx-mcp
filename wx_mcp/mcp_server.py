"""Minimal Model Context Protocol server (JSON-RPC 2.0).

Two transports are provided:

* ``stdio``    - one JSON-RPC message per line on stdin/stdout (local client).
* ``http``     - streamable HTTP endpoint (remote-capable client).

Only the ``tools`` capability is exposed, which is all wx-mcp needs.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .tools import ToolRegistry

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "wx-mcp"


class McpServer:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def handle_jsonrpc(self, body: dict[str, Any]) -> dict[str, Any] | None:
        req_id = body.get("id")
        method = body.get("method", "")

        if body.get("jsonrpc") != "2.0" or not method:
            return _error(req_id, -32600, "Invalid Request")

        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if method == "initialize":
            return _result(
                req_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                    "instructions": (
                        "WeChat message push MCP. Use tools/list to discover "
                        "the available account and message tools."
                    ),
                },
            )

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return _result(req_id, {})

        if method == "tools/list":
            return _result(req_id, {"tools": self.registry.list_tools()})

        if method == "tools/call":
            return self._tools_call(req_id, params)

        return _error(req_id, -32601, f"Method not found: {method}")

    def _tools_call(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(name, str) or not name:
            return _error(req_id, -32602, "Missing tool name")
        if arguments is not None and not isinstance(arguments, dict):
            return _error(req_id, -32602, "Tool arguments must be an object")

        try:
            result = self.registry.call(name, arguments or {})
            text = json.dumps(result, ensure_ascii=False, indent=2)
            return _result(
                req_id,
                {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the MCP client
            return _result(
                req_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Tool execution error: {type(e).__name__}: {e}",
                        }
                    ],
                    "isError": True,
                },
            )


def _result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


# ---------------------------------------------------------------------------
# stdio transport
# ---------------------------------------------------------------------------


def run_stdio(server: McpServer) -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for raw_line in stdin:
        if not raw_line.strip():
            continue
        try:
            body = json.loads(raw_line.decode("utf-8"))
        except json.JSONDecodeError as e:
            stdout.write(
                (json.dumps(_error(None, -32700, f"Parse error: {e}")) + "\n").encode(
                    "utf-8"
                )
            )
            stdout.flush()
            continue

        try:
            response = server.handle_jsonrpc(body)
        except Exception as e:  # noqa: BLE001
            response = _error(body.get("id"), -32603, str(e))

        if response is not None:
            stdout.write(
                (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
            )
            stdout.flush()


# ---------------------------------------------------------------------------
# streamable HTTP transport
# ---------------------------------------------------------------------------


class _HttpHandler(BaseHTTPRequestHandler):
    server_ref: McpServer | None = None

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Mcp-Session-Id")

    def _send_bytes(
        self,
        data: bytes,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self._cors()
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _send_json(
        self,
        obj: Any,
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._send_bytes(
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            status,
            extra_headers=extra_headers,
        )

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] in ("/", "/mcp", "/health"):
            self._send_json(
                {
                    "name": SERVER_NAME,
                    "version": __version__,
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "transport": "streamable-http",
                }
            )
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] not in ("/", "/mcp"):
            self._send_json({"error": "not found"}, 404)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json(_error(None, -32700, f"Parse error: {e}"), 400)
            return
        except Exception as e:  # noqa: BLE001
            self._send_json(_error(None, -32700, f"Invalid request: {e}"), 400)
            return

        session_id = self.headers.get("Mcp-Session-Id")
        extra_headers = {"Mcp-Session-Id": session_id} if session_id else None

        server = self.server_ref
        if server is None:
            self._send_json(_error(body.get("id"), -32603, "Server not initialized"), 500)
            return

        try:
            response = server.handle_jsonrpc(body)
        except Exception as e:  # noqa: BLE001
            response = _error(body.get("id"), -32603, str(e))

        if response is None:
            self.send_response(202)
            self._cors()
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send_json(response, extra_headers=extra_headers)


def run_http(server: McpServer, host: str = "127.0.0.1", port: int = 18080) -> None:
    _HttpHandler.server_ref = server
    httpd = ThreadingHTTPServer((host, port), _HttpHandler)
    print(f"[wx-mcp] MCP server listening on http://{host}:{port}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
