#!/usr/bin/env python3
"""
MCP (Model Context Protocol) HTTP Server
=========================================
Standard-library-only implementation (Python 3.8+).
No third-party dependencies required.

Protocol:   MCP 2024-11-05
Transport:  HTTP + Server-Sent Events (SSE)

Quick start
-----------
    python server.py                        # http://localhost:8080
    python server.py --port 9000
    python server.py --tools-dir ./tools    # explicit tools directory

VS Code / GitHub Copilot  (.vscode/mcp.json)
--------------------------------------------
    {
      "servers": {
        "my-server": { "type": "http", "url": "http://localhost:8080/sse" }
      }
    }

Auto-discovery
--------------
On startup the server scans every *.py file in --tools-dir, imports it,
and calls  module.register(registry)  when that function exists.
Drop a new file there and restart — no other changes needed.
"""

from __future__ import annotations

import argparse
import http.server
import importlib.util
import inspect
import json
import logging
import os
import queue
import sys
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("mcp_server")


# ── Tool Registry ─────────────────────────────────────────────────────────────


class ToolRegistry:
    """Central registry for MCP tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._handlers: Dict[str, Callable] = {}

    def register(
        self,
        name: Optional[str] = None,
        description: str = "",
        parameters: Optional[Dict] = None,
    ) -> Callable:
        """Decorator that registers a function as an MCP tool.

        Example usage in tools/*.py::

            def register(registry):
                @registry.register(name="hello", description="Say hello.")
                def hello(name: str) -> str:
                    return f"Hello, {name}!"
        """

        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            schema = parameters or _infer_schema(fn)
            self._tools[tool_name] = {
                "name": tool_name,
                "description": description or (fn.__doc__ or "").strip(),
                "inputSchema": schema,
            }
            self._handlers[tool_name] = fn
            log.debug("Registered tool: %s", tool_name)
            return fn

        return decorator

    def discover(self, directory: str) -> int:
        """Scan *directory* for Python modules and call register() on each.

        Each module should expose::

            def register(registry: ToolRegistry) -> None: ...

        Returns the number of new tools registered.
        """
        before = len(self._tools)
        if not os.path.isdir(directory):
            log.warning("Tools directory not found: %s  (skipping)", directory)
            return 0

        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            filepath = os.path.join(directory, filename)
            module_name = f"_mcp_tool_{filename[:-3]}"
            try:
                spec = importlib.util.spec_from_file_location(
                    module_name, filepath
                )
                mod = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = mod
                spec.loader.exec_module(mod)
                if callable(getattr(mod, "register", None)):
                    mod.register(self)
                    log.info("Loaded tool module: %s", filename)
                else:
                    log.warning(
                        "Module %s has no register() — skipped", filename
                    )
            except Exception as exc:
                log.error("Failed to load %s: %s", filename, exc)

        discovered = len(self._tools) - before
        log.info(
            "Auto-discovery: %d new tool(s) from %s", discovered, directory
        )
        return discovered

    def list_tools(self) -> List[Dict]:
        return list(self._tools.values())

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name not in self._handlers:
            raise ValueError(f"Unknown tool: {name!r}")
        return self._handlers[name](**arguments)

    @property
    def tool_names(self) -> List[str]:
        return sorted(self._tools.keys())


# ── Schema inference ──────────────────────────────────────────────────────────

_PY_TO_JSON: Dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _infer_schema(fn: Callable) -> Dict:
    """Build a minimal JSON Schema from a function's type annotations."""
    sig = inspect.signature(fn)
    props: Dict[str, Any] = {}
    required: List[str] = []
    for pname, param in sig.parameters.items():
        json_type = _PY_TO_JSON.get(param.annotation, "string")
        props[pname] = {"type": json_type, "description": ""}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema: Dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


# ── Session store ─────────────────────────────────────────────────────────────


class SessionStore:
    """Thread-safe map: session ID → response queue."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, queue.Queue] = {}

    def create(self) -> Tuple[str, queue.Queue]:
        sid = str(uuid.uuid4())
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._sessions[sid] = q
        return sid, q

    def get(self, sid: str) -> Optional[queue.Queue]:
        with self._lock:
            return self._sessions.get(sid)

    def remove(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)


_sessions = SessionStore()


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────


def _ok(req_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def _err(req_id: Any, code: int, message: str, data: Any = None) -> str:
    payload: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = str(data)
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": payload})


# ── MCP constants ─────────────────────────────────────────────────────────────

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mcp-server", "version": "1.0.0"}
SERVER_CAPABILITIES = {
    "tools": {"listChanged": True},
    "resources": {},
    "prompts": {},
}


# ── Request dispatcher ────────────────────────────────────────────────────────


def dispatch(msg: Dict, tool_reg: ToolRegistry) -> Optional[str]:
    """Handle one JSON-RPC message; return serialised response or None."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    try:
        if method == "initialize":
            return _ok(
                req_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": SERVER_INFO,
                    "capabilities": SERVER_CAPABILITIES,
                },
            )
        if method == "initialized":
            return None
        if method == "ping":
            return _ok(req_id, {})
        if method == "tools/list":
            return _ok(req_id, {"tools": tool_reg.list_tools()})
        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                result = tool_reg.call_tool(tool_name, arguments)
                return _ok(
                    req_id,
                    {
                        "content": [{"type": "text", "text": str(result)}],
                        "isError": False,
                    },
                )
            except Exception as exc:
                log.warning("Tool %r raised: %s", tool_name, exc)
                return _ok(
                    req_id,
                    {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                )
        if method == "resources/list":
            return _ok(req_id, {"resources": []})
        if method == "resources/read":
            return _err(req_id, -32601, "resources/read not implemented")
        if method == "prompts/list":
            return _ok(req_id, {"prompts": []})
        if method == "prompts/get":
            return _err(req_id, -32601, "prompts/get not implemented")
        if req_id is None:
            return None
        return _err(req_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        log.exception("Dispatch error for %r", method)
        return _err(req_id, -32603, "Internal error", exc)


# ── HTTP handler ──────────────────────────────────────────────────────────────


class MCPHandler(http.server.BaseHTTPRequestHandler):
    """
    Supports two MCP HTTP transports simultaneously:

    Streamable HTTP (MCP 2025-03-26) — used by VS Code / GitHub Copilot:
      POST /sse          Receive JSON-RPC, return direct HTTP response.
      GET  /sse          Optional SSE stream for server-initiated messages.

    Legacy SSE (MCP 2024-11-05):
      GET  /sse          Open SSE stream; first event gives POST endpoint URL.
      POST /messages     Receive JSON-RPC; response delivered over SSE.

    Both:
      GET  /health       Server status + registered tool list.
    """

    tool_registry: ToolRegistry = None
    base_url: str = ""

    def log_message(self, fmt, *args):
        log.info("HTTP  %-20s  %s", self.address_string(), fmt % args)

    def log_error(self, fmt, *args):
        log.error("HTTP  %-20s  %s", self.address_string(), fmt % args)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/sse", "/mcp"):
            # Streamable HTTP: GET opens an optional SSE stream for server
            # notifications.  Legacy SSE transport also uses GET /sse.
            self._handle_sse()
        elif path == "/health":
            self._json(
                200,
                {
                    "status": "ok",
                    "server": SERVER_INFO,
                    "protocol_version": PROTOCOL_VERSION,
                    "active_sessions": _sessions.active_count,
                    "tools": self.tool_registry.tool_names,
                },
            )
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path in ("/", "/sse", "/mcp"):
            # Streamable HTTP transport (VS Code / Copilot): respond directly
            # in the HTTP response body — no SSE round-trip needed.
            self._handle_jsonrpc_direct()
        elif path == "/messages":
            # Legacy SSE transport: push response onto the session's SSE queue.
            self._handle_message()
        else:
            self._json(404, {"error": "not found"})

    def _handle_jsonrpc_direct(self):
        """Streamable HTTP transport: process JSON-RPC and respond inline."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            msg = json.loads(body)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"invalid JSON: {exc}"})
            return

        log.debug("JSON-RPC  method=%s", msg.get("method"))
        response = dispatch(msg, self.tool_registry)

        if response is not None:
            resp_bytes = response.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self._cors()
            self.end_headers()
            self.wfile.write(resp_bytes)
        else:
            # Notification — protocol requires no response body
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()

    def _handle_sse(self):
        sid, q = _sessions.create()
        endpoint = f"{self.base_url}/messages?sessionId={sid}"
        log.info("SSE open  session=%s  active=%d", sid, _sessions.active_count)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()

        self._sse("endpoint", endpoint)

        try:
            while True:
                try:
                    payload = q.get(timeout=20)
                    if payload is None:
                        break
                    self._sse("message", payload)
                except queue.Empty:
                    self._sse("ping", "keepalive")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            _sessions.remove(sid)
            log.info(
                "SSE close session=%s  active=%d", sid, _sessions.active_count
            )

    def _sse(self, event, data):
        try:
            self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode())
            self.wfile.flush()
        except OSError as exc:
            raise BrokenPipeError from exc

    def _handle_message(self):
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(self.path).query)
        sid = (qs.get("sessionId") or [""])[0]
        q = _sessions.get(sid)
        if q is None:
            self._json(404, {"error": f"unknown sessionId: {sid!r}"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            msg = json.loads(body)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"invalid JSON: {exc}"})
            return
        response = dispatch(msg, self.tool_registry)
        if response is not None:
            q.put(response)
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


# ── Built-in tools ────────────────────────────────────────────────────────────


def _register_builtin_tools(reg: ToolRegistry) -> None:
    import datetime
    import platform
    import socket as _socket

    @reg.register(
        name="get_current_time",
        description="Returns the current UTC date and time in ISO 8601 format.",
    )
    def get_current_time() -> str:
        return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    @reg.register(
        name="get_server_info",
        description="Returns hostname, platform, Python version, and registered tools.",
    )
    def get_server_info() -> str:
        return json.dumps(
            {
                "hostname": _socket.gethostname(),
                "platform": platform.system(),
                "platform_release": platform.release(),
                "python_version": platform.python_version(),
                "mcp_server": SERVER_INFO,
                "registered_tools": reg.tool_names,
            },
            indent=2,
        )

    @reg.register(
        name="echo",
        description="Echoes the provided message back unchanged. Useful for testing.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Text to echo."},
            },
            "required": ["message"],
        },
    )
    def echo(message: str) -> str:
        return message

    @reg.register(
        name="list_registered_tools",
        description="Lists all tools currently registered on this MCP server.",
    )
    def list_registered_tools() -> str:
        return "\n".join(
            f"- {t['name']}: {t['description']}" for t in reg.list_tools()
        )


# ── Server factory ────────────────────────────────────────────────────────────


def make_server(
    host: str, port: int, tool_reg: ToolRegistry
) -> http.server.HTTPServer:
    class _Handler(MCPHandler):
        pass

    _Handler.tool_registry = tool_reg
    _Handler.base_url = f"http://{host}:{port}"
    return http.server.ThreadingHTTPServer((host, port), _Handler)


registry = ToolRegistry()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP HTTP server — stdlib only",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--tools-dir",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "tools"
        ),
        metavar="DIR",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    _register_builtin_tools(registry)
    registry.discover(args.tools_dir)

    log.info(
        "MCP server  http://%s:%s  (%d tools)",
        args.host,
        args.port,
        len(registry.list_tools()),
    )
    log.info("Tools:   %s", registry.tool_names)
    log.info("SSE:     http://%s:%s/sse", args.host, args.port)
    log.info("Health:  http://%s:%s/health", args.host, args.port)

    server = make_server(args.host, args.port, registry)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
