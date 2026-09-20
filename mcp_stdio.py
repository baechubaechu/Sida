#!/usr/bin/env python3
"""Minimal MCP client over newline-delimited JSON-RPC (stdio)."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class McpError(RuntimeError):
    pass


class McpStdioClient:
    """Talk to an MCP server launched as a child process (NDJSON framing)."""

    def __init__(self, command: list[str], *, cwd: Path | None = None, timeout: float = 60.0):
        if not command:
            raise McpError("empty MCP command")
        self.timeout = timeout
        self._id = 0
        self._lock = threading.Lock()
        try:
            self._proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(cwd) if cwd else None,
            )
        except OSError as exc:
            raise McpError(f"failed to start MCP server: {exc}") from exc
        if self._proc.stdin is None or self._proc.stdout is None:
            raise McpError("MCP server pipes unavailable")
        self._initialize()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, obj: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _read_message(self, *, timeout: float | None = None) -> dict[str, Any]:
        assert self._proc.stdout is not None
        wait = self.timeout if timeout is None else timeout
        holder: dict[str, Any] = {}

        def worker() -> None:
            try:
                line = self._proc.stdout.readline()
                holder["line"] = line
            except Exception as exc:  # noqa: BLE001
                holder["exc"] = exc

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(wait)
        if t.is_alive():
            raise McpError(f"MCP read timed out after {wait}s")
        if "exc" in holder:
            raise McpError(str(holder["exc"]))
        line = holder.get("line") or ""
        if not line:
            raise McpError("MCP server closed stdout")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise McpError(f"invalid MCP JSON: {line[:200]}") from exc

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            req_id = self._next_id()
            msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                msg["params"] = params
            self._send(msg)
            # Skip notifications until matching id
            deadline_reads = 40
            for _ in range(deadline_reads):
                data = self._read_message()
                if data.get("id") != req_id:
                    # notification or unrelated — ignore
                    continue
                if "error" in data:
                    err = data["error"]
                    raise McpError(f"{method}: {err}")
                return data.get("result")
            raise McpError(f"no response for {method}")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        with self._lock:
            msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                msg["params"] = params
            self._send(msg)

    def _initialize(self) -> None:
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sida-rhino-modeler", "version": "0.1"},
            },
        )
        self.notify("notifications/initialized")

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list") or {}
        tools = result.get("tools") if isinstance(result, dict) else None
        return list(tools or [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return _unwrap_tool_result(result)

    def close(self) -> None:
        if self._proc.poll() is not None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

    def __enter__(self) -> McpStdioClient:
        return self

    def __exit__(self, *_) -> None:
        self.close()


def _unwrap_tool_result(result: Any) -> Any:
    """Normalize MCP tool result content to a Python value / string."""
    if not isinstance(result, dict):
        return result
    if result.get("isError"):
        content = result.get("content") or []
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
        raise McpError("; ".join(texts) or "tool error")
    content = result.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
        joined = "\n".join(texts).strip()
        if not joined:
            return result
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return joined
    return result


def iter_default_rhino_commands() -> Iterator[list[str]]:
    """Candidate argv lists for the Rhino MCP router."""
    import os

    env = os.environ.get("SIDA_RHINO_MCP", "").strip()
    if env:
        yield [env]
    yield [
        str(
            Path.home()
            / "AppData"
            / "Roaming"
            / "McNeel"
            / "Rhinoceros"
            / "packages"
            / "8.0"
            / "Rhino-MCP-Platform"
            / "0.2.1-wip"
            / "router"
            / "win-x64"
            / "rhino-mcp-router.exe"
        )
    ]
