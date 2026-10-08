"""Read-only MCP tools used by the capability-center demonstration."""

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP


demo_mcp = FastMCP(
    "Agent Base Demo",
    instructions="Two read-only demonstration tools: current UTC time and integer addition.",
    stateless_http=True,
    json_response=True,
)


@demo_mcp.tool()
def current_time() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@demo_mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return their exact sum."""
    return a + b
