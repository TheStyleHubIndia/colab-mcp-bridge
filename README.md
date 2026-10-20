# Google Colab MCP Bridge

A personal MCP bridge hosted on Render. It queues Python snippets for a Google Colab notebook; it does **not** execute submitted code on the Render server.

## Current architecture

- MCP endpoint: `https://colab-mcp-bridge-3jkv.onrender.com/mcp`
- Health check: `https://colab-mcp-bridge-3jkv.onrender.com/health`
- `submit_python_task`: queue a code snippet for Colab.
- `get_task_result`: retrieve the result by task ID.
- Colab agent: `colab_agent.py`; displays code and requires the user to type `RUN` before execution.
- Colab polling endpoints require the `COLAB_BRIDGE_TOKEN` environment variable on Render.

## Setup

1. In Render, set a strong secret environment variable named `COLAB_BRIDGE_TOKEN`. Never commit this token to GitHub.
2. Open Google Colab and create a Python notebook.
3. Copy the contents of `colab_agent.py` into a cell and run it. Enter the same token when prompted.
4. Add the MCP endpoint above to a ChatGPT custom MCP connection if that feature is available in your account.
5. Use `submit_python_task` to queue code. Inspect it in Colab and type `RUN` only when you trust it. Otherwise type anything else to reject it.
6. Use `get_task_result` with the task ID to retrieve output.

## Important limitations

- The task queue and results are in memory. They can be lost when Render restarts or sleeps.
- A Colab runtime must remain connected and the agent cell must be running.
- Python approved in Colab can access that notebook's files, runtime and any credentials available to the runtime. Review every snippet; never paste secrets into task code.
- This is a personal prototype, not a production execution service. Keep the token private.
- ChatGPT custom MCP support depends on account/UI availability.
