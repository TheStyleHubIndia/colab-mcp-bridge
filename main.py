from mcp.server.fastmcp import FastMCP

mcp = FastMCP("colab-mcp-bridge")

@mcp.tool()
def bridge_status() -> str:
    """Check whether the Colab MCP bridge server is running."""
    return "MCP bridge is online. Colab execution is not configured yet."

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
