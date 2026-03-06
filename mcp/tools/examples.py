"""
Example auto-discovered tool module.
=====================================
This file is loaded automatically because it lives in the tools/ directory
and exposes a  register(registry)  function.

To add a tool: add another @registry.register block inside register().
To add a new category: copy this file to a new name — the server picks it up
on next restart automatically.

All tools here use only the Python standard library.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server import ToolRegistry


def register(registry: "ToolRegistry") -> None:
    """Called by the server's auto-discovery on startup."""

    # ── Network tools ─────────────────────────────────────────────────────

    @registry.register(
        name="dns_lookup",
        description=(
            "Resolves a hostname to its IP address(es) using the system DNS resolver."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hostname": {
                    "type": "string",
                    "description": "Hostname or FQDN to resolve.",
                },
            },
            "required": ["hostname"],
        },
    )
    def dns_lookup(hostname: str) -> str:
        try:
            results = socket.getaddrinfo(hostname, None)
            seen: set = set()
            addrs = []
            for r in results:
                addr = r[4][0]
                if addr not in seen:
                    seen.add(addr)
                    addrs.append(addr)
            return json.dumps(
                {"hostname": hostname, "addresses": addrs, "resolved": True}
            )
        except socket.gaierror as exc:
            return json.dumps(
                {
                    "hostname": hostname,
                    "addresses": [],
                    "resolved": False,
                    "error": str(exc),
                }
            )

    @registry.register(
        name="check_port",
        description="Checks whether a TCP port on a remote host is reachable. Returns latency in ms.",
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Hostname or IP."},
                "port": {
                    "type": "integer",
                    "description": "TCP port (1-65535).",
                },
                "timeout": {
                    "type": "number",
                    "description": "Connection timeout in seconds (default 3).",
                },
            },
            "required": ["host", "port"],
        },
    )
    def check_port(host: str, port: int, timeout: float = 3.0) -> str:
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                return json.dumps(
                    {
                        "host": host,
                        "port": port,
                        "reachable": True,
                        "latency_ms": latency_ms,
                    }
                )
        except OSError as exc:
            return json.dumps(
                {
                    "host": host,
                    "port": port,
                    "reachable": False,
                    "error": str(exc),
                }
            )

    # ── Filesystem tools ──────────────────────────────────────────────────

    @registry.register(
        name="list_directory",
        description="Lists the contents of a directory with entry type and file size.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory.",
                },
            },
            "required": ["path"],
        },
    )
    def list_directory(path: str) -> str:
        abs_path = os.path.realpath(path)
        if not os.path.exists(abs_path):
            return json.dumps({"error": f"Path does not exist: {path}"})
        if not os.path.isdir(abs_path):
            return json.dumps({"error": f"Not a directory: {path}"})

        entries = []
        for entry in sorted(
            os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name)
        ):
            stat = entry.stat()
            entries.append(
                {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": stat.st_size if entry.is_file() else None,
                }
            )
        return json.dumps(
            {"path": abs_path, "entry_count": len(entries), "entries": entries},
            indent=2,
        )

    @registry.register(
        name="read_text_file",
        description="Reads a plain-text file. Optionally limits to a line range.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file."},
                "start_line": {
                    "type": "integer",
                    "description": "First line (1-based). Default 1.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line (1-based). Default: all.",
                },
            },
            "required": ["path"],
        },
    )
    def read_text_file(
        path: str, start_line: int = 1, end_line: int = 0
    ) -> str:
        abs_path = os.path.realpath(path)
        if not os.path.isfile(abs_path):
            return json.dumps({"error": f"File not found: {path}"})
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as exc:
            return json.dumps({"error": str(exc)})
        total = len(lines)
        lo = max(1, start_line) - 1
        hi = end_line if end_line > 0 else total
        selected = lines[lo:hi]
        return json.dumps(
            {
                "path": abs_path,
                "total_lines": total,
                "returned_lines": f"{lo + 1}-{lo + len(selected)}",
                "content": "".join(selected),
            }
        )

    # ── System tools ──────────────────────────────────────────────────────

    @registry.register(
        name="get_environment_variable",
        description=(
            "Returns the value of a named environment variable. "
            "Variables whose names contain PASSWORD, SECRET, TOKEN, KEY, or CREDENTIAL are blocked."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Environment variable name.",
                },
            },
            "required": ["name"],
        },
    )
    def get_environment_variable(name: str) -> str:
        _BLOCKED = {
            "PASSWORD",
            "SECRET",
            "TOKEN",
            "KEY",
            "CREDENTIAL",
            "PRIVATE",
        }
        if any(kw in name.upper() for kw in _BLOCKED):
            return json.dumps(
                {"error": "Access denied: blocked keyword in variable name."}
            )
        value = os.environ.get(name)
        return json.dumps(
            {"name": name, "value": value, "set": value is not None}
        )

    @registry.register(
        name="get_system_metrics",
        description=(
            "Returns lightweight system metrics: CPU count, load averages (Unix), "
            "and memory info from /proc/meminfo (Linux)."
        ),
    )
    def get_system_metrics() -> str:
        result: dict = {
            "platform": platform.system(),
            "cpu_count": os.cpu_count(),
        }
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()
            result["load_avg"] = {
                "1min": round(load[0], 2),
                "5min": round(load[1], 2),
                "15min": round(load[2], 2),
            }
        if os.path.isfile("/proc/meminfo"):
            mem: dict = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    parts = line.split()
                    if parts[0] in ("MemTotal:", "MemAvailable:", "MemFree:"):
                        mem[parts[0].rstrip(":")] = int(parts[1]) * 1024
            result["memory_bytes"] = mem
        return json.dumps(result, indent=2)

    # ── Lookup / data tools ───────────────────────────────────────────────
    # Demonstrates key/value lookups — replace the dict with a real DB
    # query, YAML load, REST API call, etc.

    _SERVICE_CATALOG: dict = {
        "web": {"port": 443, "protocol": "https", "team": "platform"},
        "api": {"port": 8443, "protocol": "https", "team": "backend"},
        "db": {"port": 5432, "protocol": "postgresql", "team": "data"},
        "cache": {"port": 6379, "protocol": "redis", "team": "platform"},
    }

    @registry.register(
        name="lookup_service",
        description=(
            "Looks up a service in the internal service catalog (port, protocol, team). "
            "Use 'all' to list known services."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Service name (e.g. 'web', 'api', 'db') or 'all'.",
                },
            },
            "required": ["service_name"],
        },
    )
    def lookup_service(service_name: str) -> str:
        name = service_name.lower().strip()
        if name in ("all", ""):
            return json.dumps({"services": sorted(_SERVICE_CATALOG.keys())})
        entry = _SERVICE_CATALOG.get(name)
        if entry is None:
            return json.dumps(
                {
                    "error": f"{service_name!r} not found.",
                    "available": sorted(_SERVICE_CATALOG.keys()),
                }
            )
        return json.dumps({"service": name, **entry})
