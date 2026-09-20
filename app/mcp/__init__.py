"""
app/mcp
=======
HomeOps MCP server package (Phase 2).

Exposes HomeOps capabilities as MCP tools over Streamable HTTP transport.

Modules
-------
server.py   MCPServer wiring and Streamable HTTP startup entry point.
tools.py    Thin adapter functions for each MCP tool.
context.py  Shared AppContext (home_state, engine, history) singleton.

NOT implemented yet
-------------------
* Alexa+ integration
* Strands agent orchestration
* Amazon Bedrock LLM calls
"""
