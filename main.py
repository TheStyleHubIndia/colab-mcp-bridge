import logging
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

PORT = int(os.environ.get("PORT", "10000"))
BRIDGE_TOKEN = os.environ.get("COLAB_BRIDGE_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
INSTANCE_ID = os.environ.get("RENDER_INSTANCE_ID", os.environ.get("HOSTNAME", "unknown"))
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("colab-mcp-bridge")

mcp = FastMCP("colab-mcp-bridge", host="0.0.0.0", port=PORT)


@asynccontextmanager
async def lifespan(_app):
    if DATABASE_URL:
        _init_db()
        logger.info("persistent_storage=postgres instance=%s", INSTANCE_ID)
    else:
        logger.warning("persistent_storage=memory; set DATABASE_URL for restart-safe shared task storage")
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Google Colab MCP Bridge", version="0.3.0", lifespan=lifespan)
_tasks = deque(maxlen=50)
_results = {}
_known_task_ids = set()
_lock = Lock()


def _db_connect():
    if not DATABASE_URL:
        return None
    import psycopg
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def _init_db():
    with _db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS colab_tasks (
                task_id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'claimed', 'completed', 'failed', 'rejected')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                claimed_at TIMESTAMPTZ
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS colab_results (
                task_id TEXT PRIMARY KEY REFERENCES colab_tasks(task_id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK (status IN ('completed', 'failed', 'rejected')),
                output TEXT NOT NULL DEFAULT '',
                received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


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
    storage = "PostgreSQL persistence enabled" if DATABASE_URL else "WARNING: in-memory storage only; configure DATABASE_URL for persistence"
    return f"MCP bridge is online. {storage}. Colab execution still requires explicit notebook approval."


@mcp.tool()
def submit_python_task(code: str, description: str = "Python task") -> str:
    """Queue Python code for Colab. The server never executes it; Colab requires explicit user approval."""
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
    try:
        if DATABASE_URL:
            with _db_connect() as conn:
                conn.execute(
                    "INSERT INTO colab_tasks (task_id, description, code) VALUES (%s, %s, %s)",
                    (task["task_id"], task["description"], task["code"]),
                )
        else:
            with _lock:
                _tasks.append(task)
                _known_task_ids.add(task["task_id"])
    except Exception:
        logger.exception("task_enqueue_failed task_id=%s instance=%s", task["task_id"], INSTANCE_ID)
        return "Task was not queued because storage failed. Check bridge logs and DATABASE_URL."
    logger.info("task_queued task_id=%s storage=%s instance=%s", task["task_id"], "postgres" if DATABASE_URL else "memory", INSTANCE_ID)
    suffix = "stored persistently" if DATABASE_URL else "stored in memory only; it may be lost on restart"
    return f"Queued task {task['task_id']} ({suffix}). It will only run if you approve it in Colab."


@app.get("/")
def home():
    return {
        "service": "Google Colab MCP Bridge",
        "status": "online",
        "mcp_endpoint": "/mcp",
        "execution": "Colab-only, with explicit notebook approval",
        "storage": "postgres" if DATABASE_URL else "memory",
    }


@app.get("/health")
def health():
    return {"status": "ok", "storage": "postgres" if DATABASE_URL else "memory"}


@app.get("/colab/next")
def next_task(authorization: Optional[str] = Header(default=None)):
    _require_token(authorization.removeprefix("Bearer ") if authorization else None)
    if DATABASE_URL:
        try:
            with _db_connect() as conn:
                row = conn.execute("""
                    WITH candidate AS (
                        SELECT task_id FROM colab_tasks
                        WHERE status = 'queued'
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED LIMIT 1
                    )
                    UPDATE colab_tasks AS t
                    SET status = 'claimed', claimed_at = NOW()
                    FROM candidate
                    WHERE t.task_id = candidate.task_id
                    RETURNING t.task_id, t.description, t.code,
                              EXTRACT(EPOCH FROM t.created_at)::BIGINT AS created_at
                """).fetchone()
            if not row:
                return {"task": None}
            return {"task": {"task_id": row[0], "description": row[1], "code": row[2], "created_at": row[3]}}
        except Exception:
            logger.exception("task_claim_failed instance=%s", INSTANCE_ID)
            raise HTTPException(status_code=503, detail="Task storage temporarily unavailable.")
    with _lock:
        if not _tasks:
            return {"task": None}
        task = _tasks.popleft()
    return {"task": task}


@app.post("/colab/result")
def post_result(body: ResultBody, authorization: Optional[str] = Header(default=None)):
    _require_token(authorization.removeprefix("Bearer ") if authorization else None)
    try:
        if DATABASE_URL:
            with _db_connect() as conn:
                exists = conn.execute("SELECT 1 FROM colab_tasks WHERE task_id = %s", (body.task_id,)).fetchone()
                if not exists:
                    logger.warning("result_unknown_task task_id=%s instance=%s", body.task_id, INSTANCE_ID)
                    raise HTTPException(status_code=404, detail="Unknown task_id; result was not stored.")
                conn.execute("""
                    INSERT INTO colab_results (task_id, status, output)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (task_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        output = EXCLUDED.output,
                        received_at = NOW()
                """, (body.task_id, body.status, body.output))
                conn.execute("UPDATE colab_tasks SET status = %s WHERE task_id = %s", (body.status, body.task_id))
        else:
            with _lock:
                if body.task_id not in _known_task_ids:
                    logger.warning("result_unknown_task task_id=%s instance=%s", body.task_id, INSTANCE_ID)
                    raise HTTPException(status_code=404, detail="Unknown task_id; result was not stored.")
                _results[body.task_id] = {
                    "status": body.status,
                    "output": body.output,
                    "received_at": int(time.time()),
                }
        logger.info("result_saved task_id=%s status=%s storage=%s instance=%s output_chars=%s",
                    body.task_id, body.status, "postgres" if DATABASE_URL else "memory", INSTANCE_ID, len(body.output))
        return {"ok": True, "task_id": body.task_id, "status": body.status, "storage": "postgres" if DATABASE_URL else "memory"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("result_save_failed task_id=%s instance=%s", body.task_id, INSTANCE_ID)
        raise HTTPException(status_code=503, detail="Result could not be persisted; retry the request.")


@mcp.tool()
def get_task_result(task_id: str) -> str:
    """Read a Colab result by task ID from shared PostgreSQL storage, or memory when DATABASE_URL is not configured."""
    try:
        if DATABASE_URL:
            with _db_connect() as conn:
                row = conn.execute("""
                    SELECT r.status, r.output, r.received_at
                    FROM colab_results r
                    WHERE r.task_id = %s
                """, (task_id,)).fetchone()
            result = {"status": row[0], "output": row[1], "received_at": row[2]} if row else None
        else:
            with _lock:
                result = _results.get(task_id)
    except Exception:
        logger.exception("result_lookup_failed task_id=%s instance=%s", task_id, INSTANCE_ID)
        return "Result lookup failed because storage is unavailable. Check bridge logs."
    if not result:
        return "No result received for this task ID yet. Confirm the exact task ID and that Colab printed 'Result sent to bridge'."
    return f"Status: {result['status']}\nOutput:\n{result['output']}"


app.mount("/", mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
