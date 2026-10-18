"""
app/mcp/client.py
=================
HomeOps MCP client abstraction.

Provides a unified client interface for communicating with the HomeOps MCP server:
  - Over Streamable HTTP (http://<host>:<port>/mcp)
  - In-process direct dispatch (for deterministic testing & standalone CLI simulation)

Preserves the separation of concerns:
  Alexa Adapter -> HomeOpsMCPClient -> [Streamable HTTP | In-Process] -> HomeOps MCP Server -> Services
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Optional

from app.mcp.context import AppContext, app_context as _default_context

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Base exception for MCP client errors."""


class MCPCommunicationError(MCPClientError):
    """Raised when communication with the MCP server fails."""


class MCPToolExecutionError(MCPClientError):
    """Raised when an MCP tool returns an error status."""


class HomeOpsMCPClient:
    """Client for the HomeOps MCP server.

    Parameters
    ----------
    base_url:
        Base URL of the Streamable HTTP endpoint (e.g. 'http://127.0.0.1:8000/mcp').
        If provided, the client communicates over HTTP.
    server:
        Direct MCPServer instance for in-process dispatch.
    context:
        AppContext for in-process dependency access (used for incident history queries).
    timeout_seconds:
        Network request timeout in seconds.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        server: Optional[Any] = None,
        context: Optional[AppContext] = None,
        timeout_seconds: float = 10.0,
        transport: Optional[Any] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self._server = server
        self._context = context or _default_context
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self.call_audit_log: list[dict[str, Any]] = []

        # If neither base_url nor server is provided, lazy-create default in-process server
        if not self.base_url and not self._server:
            from app.mcp.server import create_server
            self._server = create_server(context=self._context)

    # ---------------------------------------------------------------------- #
    # Core dispatch methods                                                   #
    # ---------------------------------------------------------------------- #

    async def call_tool(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Invoke an MCP tool and return its structured result.

        Parameters
        ----------
        name:
            Tool name (e.g. 'get_home_state', 'investigate_incident').
        arguments:
            Dictionary of tool arguments.

        Returns
        -------
        dict[str, Any]
            The structured dictionary returned by the tool.

        Raises
        ------
        MCPCommunicationError:
            If network connection or transport fails.
        MCPToolExecutionError:
            If the tool fails execution or returns an error.
        """
        args = arguments or {}
        start_time = time.time()
        transport_name = "Streamable HTTP (mcp 2.2.0)" if self.base_url else "in-process"

        try:
            if self.base_url:
                result_dict = await self._call_tool_http(name, args)
            else:
                result_dict = await self._call_tool_in_process(name, args)
        finally:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)

        audit_entry = {
            "tool": name,
            "arguments": args,
            "result": result_dict,
            "transport": transport_name,
            "latency_ms": elapsed_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.call_audit_log.append(audit_entry)
        return result_dict

    def call_tool_sync(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Synchronous wrapper for call_tool."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # In an active event loop, create a new task or run in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(self.call_tool(name, arguments)))
                return future.result(timeout=self.timeout_seconds + 5)
        else:
            return asyncio.run(self.call_tool(name, arguments))

    # ---------------------------------------------------------------------- #
    # Transport implementations                                               #
    # ---------------------------------------------------------------------- #

    async def _call_tool_in_process(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool directly via the MCPServer instance."""
        if not self._server:
            raise MCPCommunicationError("No MCPServer instance configured for in-process dispatch.")

        try:
            result = await self._server.call_tool(name, arguments)
        except Exception as exc:
            logger.error("In-process MCP tool '%s' call failed: %s", name, exc)
            raise MCPCommunicationError(f"In-process MCP tool '{name}' failed: {exc}") from exc

        return self._extract_result_dict(name, result)

    async def _call_tool_http(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool over Streamable HTTP."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        import httpx2

        try:
            timeout = httpx2.Timeout(self.timeout_seconds)
            client_kwargs: dict[str, Any] = {"timeout": timeout}
            if self._transport is not None:
                client_kwargs["transport"] = self._transport

            async with httpx2.AsyncClient(**client_kwargs) as http_client:
                async with streamable_http_client(self.base_url, http_client=http_client) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        return self._extract_result_dict(name, result)
        except Exception as exc:
            logger.error("Streamable HTTP MCP call to '%s' failed: %s", name, exc)
            raise MCPCommunicationError(
                f"Failed to communicate with MCP server at {self.base_url}: {exc}"
            ) from exc

    @staticmethod
    def _extract_result_dict(tool_name: str, result: Any) -> dict[str, Any]:
        """Extract a structured Python dict from a CallToolResult."""
        if getattr(result, "is_error", False):
            error_msg = f"Tool '{tool_name}' reported error"
            if hasattr(result, "content") and result.content:
                error_msg += f": {result.content[0].text}"
            raise MCPToolExecutionError(error_msg)

        # 1. Prefer structured_content if available
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            return structured

        # 2. Check content blocks for JSON text
        content = getattr(result, "content", None)
        if content and len(content) > 0:
            first_block = content[0]
            text = getattr(first_block, "text", None)
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    return {"result": text}

        return {}

    # ---------------------------------------------------------------------- #
    # High-level tool convenience methods                                     #
    # ---------------------------------------------------------------------- #

    async def get_home_state(self, location: Optional[str] = None) -> dict[str, Any]:
        """Query get_home_state via MCP."""
        args: dict[str, Any] = {}
        if location:
            args["location"] = location
        return await self.call_tool("get_home_state", args)

    async def get_recent_events(
        self,
        limit: int = 50,
        location: Optional[str] = None,
        device_type: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query get_recent_events via MCP."""
        args: dict[str, Any] = {"limit": limit}
        if location:
            args["location"] = location
        if device_type:
            args["device_type"] = device_type
        if event_type:
            args["event_type"] = event_type
        return await self.call_tool("get_recent_events", args)

    async def investigate_incident(
        self,
        scenario: Optional[str] = None,
        raw_events: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Run incident correlation via MCP."""
        args: dict[str, Any] = {}
        if scenario:
            args["scenario"] = scenario
        if raw_events:
            args["raw_events"] = raw_events
        return await self.call_tool("investigate_incident", args)

    async def assess_risk(
        self,
        incident_type: str,
        severity: str,
        confidence: float,
        title: str = "Incident",
        summary: str = "Risk assessment requested.",
        evidence: Optional[list[str]] = None,
        recommended_next_step: str = "Review incident.",
    ) -> dict[str, Any]:
        """Evaluate safety policy via MCP assess_risk."""
        args: dict[str, Any] = {
            "incident_type": incident_type,
            "severity": severity,
            "confidence": confidence,
            "title": title,
            "summary": summary,
            "evidence": evidence or [],
            "recommended_next_step": recommended_next_step,
        }
        return await self.call_tool("assess_risk", args)

    async def recommend_response(
        self,
        incident_type: str,
        severity: str,
        confidence: float,
        context: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get safe response recommendation via MCP."""
        args: dict[str, Any] = {
            "incident_type": incident_type,
            "severity": severity,
            "confidence": confidence,
        }
        if context:
            args["context"] = context
        return await self.call_tool("recommend_response", args)

    async def execute_safe_action(
        self,
        action_name: str,
        device_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send action request to MCP execute_safe_action boundary."""
        args: dict[str, Any] = {"action_name": action_name}
        if device_id:
            args["device_id"] = device_id
        return await self.call_tool("execute_safe_action", args)

    async def record_incident(
        self,
        incident_type: str,
        severity: str,
        confidence: float,
        title: str,
        summary: str,
        evidence: list[str],
        recommended_next_step: str,
    ) -> dict[str, Any]:
        """Record investigated incident to audit history via MCP."""
        args: dict[str, Any] = {
            "incident_type": incident_type,
            "severity": severity,
            "confidence": confidence,
            "title": title,
            "summary": summary,
            "evidence": evidence,
            "recommended_next_step": recommended_next_step,
        }
        return await self.call_tool("record_incident", args)

    async def get_incident_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Query incident history store for audit records."""
        # Queries the incident history service directly from context
        return self._context.history.get_incident_history(limit=limit)
