"""FastAPI wrapper exposing the agent over HTTP.

Run:
    uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001

The /answer endpoint accepts {question, db, tags?} and returns the
agent's final SQL, the result rows, and per-iteration history.
"""
from __future__ import annotations

import logging
import os
import time
from functools import wraps
from inspect import isawaitable
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    disable_created_metrics,
    generate_latest,
)
from pydantic import BaseModel
from fastapi.responses import Response

load_dotenv()

from agent.graph import AgentState, graph  # noqa: E402

# Langfuse callback handler. If keys are set we initialize it; failures
# are NOT swallowed - a misconfigured Langfuse should not silently
# produce zero traces.
_lf_handler: Any = None
if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
    from langfuse.langchain import CallbackHandler

    _lf_handler = CallbackHandler()


logger = logging.getLogger(__name__)


app = FastAPI()

disable_created_metrics()
metrics_registry = CollectorRegistry()

agent_runs_completed = Counter(
    "agent_runs_completed_total",
    "Completed agent executions",
    registry=metrics_registry,
)

agent_run_duration = Histogram(
    "agent_run_duration_seconds",
    "End-to-end agent latency",
    buckets=[0.1, 0.25, 0.5, 1, 2, 3, 4, 5, 7, 10],
    registry=metrics_registry,
)

class AnswerRequest(BaseModel):
    question: str
    db: str
    tags: dict[str, str] = {}


class AnswerResponse(BaseModel):
    sql: str
    rows: list[list[Any]] | None
    iterations: int
    ok: bool
    error: str | None = None
    history: list[dict[str, Any]] = []

def track_agent_metrics(func):

    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        if isawaitable(result):
            result = await result

        # Success only
        duration = time.perf_counter() - start
        agent_runs_completed.inc()
        agent_run_duration.observe(duration)
        return result

    return wrapper


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(metrics_registry), media_type=CONTENT_TYPE_LATEST)


@app.post("/answer", response_model=AnswerResponse)
@track_agent_metrics
def answer(req: AnswerRequest) -> AnswerResponse:
    state = AgentState(question=req.question, db_id=req.db)
    config: dict[str, Any] = {
        "callbacks": [_lf_handler] if _lf_handler is not None else [],
        "metadata": req.tags,
    }
    try:
        final = graph.invoke(state, config=config)
    except Exception as e:  # noqa: BLE001
        logger.exception("Exception in answer endpoint")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    sql = final.get("sql", "")
    iteration = final.get("iteration", 0)
    history = final.get("history", [])
    execution = final.get("execution")

    if execution is None:
        return AnswerResponse(
            sql=sql,
            rows=None,
            iterations=iteration,
            ok=False,
            error="agent produced no execution result",
            history=history,
        )
    if not execution.ok:
        return AnswerResponse(
            sql=sql,
            rows=None,
            iterations=iteration,
            ok=False,
            error=execution.error,
            history=history,
        )

    return AnswerResponse(
        sql=sql,
        rows=[list(r) for r in (execution.rows or [])],
        iterations=iteration,
        ok=True,
        history=history,
    )
