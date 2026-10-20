# Google Colab MCP Bridge

A personal MCP bridge hosted on Render. It queues Python snippets for a Google Colab notebook; submitted code is **not** executed on the Render server.

## Endpoints and tools

- MCP endpoint: `/mcp`
- Health check: `/health`
- `submit_python_task`: queue code for Colab.
- `get_task_result`: retrieve output by task ID.
- Colab agent: `colab_agent.py`; displays code and requires the user to type `RUN` before execution.
- `/colab/next` and `/colab/result` require `COLAB_BRIDGE_TOKEN`.

## Persistent storage

For restart-safe task and result storage, configure `DATABASE_URL` to a PostgreSQL database reachable by the Render service. On startup, the bridge creates the two required tables if they do not exist. The database user needs permission to create tables, or an administrator must create the schema before startup.

If `DATABASE_URL` is absent, the service retains a compatibility mode using in-memory storage. In that mode, tasks/results can be lost on restart and may not be shared across instances; `bridge_status` and `/health` identify the storage mode.

The result endpoint verifies the task ID in PostgreSQL before accepting a result, returns the task ID and storage mode, and logs task ID/status/storage/instance (never the bridge token or output text). Unknown task IDs return HTTP 404 instead of a misleading success response. Storage failures return HTTP 503.

## Setup

1. Set a strong `COLAB_BRIDGE_TOKEN` in Render. Never commit it to GitHub.
2. Configure `DATABASE_URL` with a PostgreSQL connection string before expecting persistence.
3. Run `colab_agent.py` in a Google Colab cell and enter the same token when prompted.
4. Review every task and type `RUN` only when you trust the code. Anything else rejects it.
5. Call `get_task_result` with the exact task ID returned when the task was queued.

## Security and limitations

- Approved Python executes in the user's Colab runtime, not on Render. It can access notebook files and credentials available to that runtime; review every snippet and never put secrets in task code.
- Keep `COLAB_BRIDGE_TOKEN` private.
- This is a personal prototype, not a production execution service.
- ChatGPT custom MCP support depends on account/UI availability.
