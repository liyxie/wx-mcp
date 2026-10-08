#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${WX_MCP_PYTHON:-$SCRIPT_DIR/.venv/bin/python}"

HOST="${WX_MCP_HOST:-0.0.0.0}"
PORT="${WX_MCP_PORT:-18080}"

RUN_DIR="$SCRIPT_DIR/run"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$RUN_DIR/wx-mcp.pid"
OUT_LOG="$LOG_DIR/wx-mcp.out.log"
ERR_LOG="$LOG_DIR/wx-mcp.err.log"

ACTION="${1:-start}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
    echo "python not found or not executable: $PYTHON" >&2
    echo "set WX_MCP_PYTHON to the venv python path, for example:" >&2
    echo "  export WX_MCP_PYTHON=/path/to/wx-mcp/.venv/bin/python" >&2
    exit 1
fi

is_running() {
    if [[ ! -f "$PID_FILE" ]]; then
        return 1
    fi
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

get_pid() {
    cat "$PID_FILE" 2>/dev/null || true
}

do_start() {
    if is_running; then
        echo "wx-mcp is already running (PID $(get_pid))."
        return
    fi

    nohup "$PYTHON" -m wx_mcp \
        --transport http \
        --host "$HOST" \
        --port "$PORT" \
        >>"$OUT_LOG" 2>>"$ERR_LOG" &

    local pid=$!
    echo "$pid" >"$PID_FILE"
    sleep 1

    if ! kill -0 "$pid" 2>/dev/null; then
        echo "wx-mcp exited immediately. Check $ERR_LOG" >&2
        rm -f "$PID_FILE"
        exit 1
    fi

    echo "wx-mcp started (PID $pid, http://${HOST}:${PORT})."
}

do_stop() {
    if ! is_running; then
        echo "wx-mcp is not running."
        rm -f "$PID_FILE"
        return
    fi

    local pid
    pid="$(get_pid)"
    kill "$pid"

    for _ in $(seq 1 20); do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.2
    done

    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    echo "wx-mcp stopped (PID $pid)."
}

do_status() {
    if ! is_running; then
        echo "wx-mcp is not running."
        return
    fi

    local pid
    pid="$(get_pid)"
    echo "wx-mcp is running (PID $pid)."

    if command -v curl >/dev/null 2>&1; then
        curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" \
            && echo \
            || echo "health check failed"
    else
        echo "curl not found; skip health check."
    fi
}

case "$ACTION" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    status)
        do_status
        ;;
    restart)
        do_stop
        sleep 1
        do_start
        ;;
    *)
        echo "usage: $0 {start|stop|status|restart}" >&2
        exit 2
        ;;
esac
