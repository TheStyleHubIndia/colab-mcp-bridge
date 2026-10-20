import os
from contextlib import asynccontextmanager
import time
import uuid
from collections import deque
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

PORT = int(os.environ.get("PORT", "10000"))
BRIDGE_TOKEN = os.environ.get("COLAB_BRIDGE_TOKEN", "")

mcp = FastMCP("colab-mcp-bridge", host="0.0.0.0", port=PORT)
@asynccontextmanager
async def lifespan(_app):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Google Colab MCP Bridge", version="0.2.0", lifespan=lifespan)

_tasks = deque(maxlen=50)
_results = {}
_lock = Lock()


def _require_token(provided: Optional[str]) -> None:
    if not BRIDGE_TOKEN:
        raise HTTPException(status_code=503, detail="Set COLAB_BRIDGE_TOKEN in Render environment variables first.")
    if not provided or provided != BRIDGE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid bridge token.")


class ResultBody(BaseModel):
    task_id: str = Field(min_length=1, max_length=80)
    status: str = Field(pattern="^(completed|failed|rejected)$")
    output: str = Field(default="", max_length=20000)


@mcp.tool()
def bridge_status() -> str:
    """Check whether the Google Colab MCP bridge server is running."""
    return "MCP bridge is online. For Colab polling, configure COLAB_BRIDGE_TOKEN in Render and run the approval-based Colab notebook agent."


@mcp.tool()
def submit_python_task(code: str, description: str = "Python task") -> str:
    """Queue Python code for the user's Colab notebook. The code is NOT run on the server. Colab must display it and get explicit user approval before execution."""
    code = code.strip()
    if not code:
        return "Rejected: code is empty."
    if len(code) > 20000:
        return "Rejected: code exceeds the 20,000 character limit."
    task = {
        "task_id": str(uuid.uuid4()),
        "description": description[:200],
        "code": code,
        "created_at": int(time.time()),
    }
    with _lock:
        _tasks.append(task)
    return f"Queued task {task['task_id']}. It will only run if the user approves it in their Colab notebook. Queue is temporary and may clear when Render restarts."


@app.get("/")
def home():
    return {
        "service": "Google Colab MCP Bridge",
        "status": "online",
        "mcp_endpoint": "/mcp",
        "execution": "Colab-only, with explicit notebook approval",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/colab/next")
def next_task(authorization: Optional[str] = Header(default=None)):
    _require_token(authorization.removeprefix("Bearer ") if authorization else None)
    with _lock:
        if not _tasks:
            return {"task": None}
        task = _tasks.popleft()
    return {"task": task}


@app.post("/colab/result")
def post_result(body: ResultBody, authorization: Optional[str] = Header(default=None)):
    _require_token(authorization.removeprefix("Bearer ") if authorization else None)
    with _lock:
        _results[body.task_id] = {
            "status": body.status,
            "output": body.output,
            "received_at": int(time.time()),
        }
    return {"ok": True}


@mcp.tool()
def get_task_result(task_id: str) -> str:
    """Read the latest result returned by the Colab notebook for a queued task."""
    with _lock:
        result = _results.get(task_id)
    if not result:
        return "No result received yet. The Colab notebook may be offline, or the task may not have been approved."
    return f"Status: {result['status']}\nOutput:\n{result['output']}"


app.mount("/", mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
