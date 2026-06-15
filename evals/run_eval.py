"""Eval runner using execution accuracy.

Reads evals/eval_set.jsonl, calls the agent at AGENT_URL on each question,
then compares the agent's SQL output to the gold SQL by *executed rows*
(canonicalized: sorted, stringified, None-coerced to empty).

Helpers (run_sql / canonicalize / matches) are provided. You implement
eval_one() and summarize().

Run:
    uv run python evals/run_eval.py --out results/eval_baseline.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = ROOT / "evals" / "eval_set.jsonl"
DEFAULT_OUT_FILE = ROOT / "results" / "eval_baseline.json"
DB_DIR = ROOT / "data" / "bird"
AGENT_URL_DEFAULT = "http://localhost:8001/answer"


# ---------- Helpers (provided) -----------------------------------------

def run_sql(db_id: str, sql: str, timeout: float = 5.0) -> tuple[bool, list[tuple] | None, str | None]:
    """Run sql against db_id in read-only mode. Returns (ok, rows, error)."""
    path = DB_DIR / f"{db_id}.sqlite"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return True, rows, None
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}"


def canonicalize(rows: list[tuple] | None) -> list[tuple] | None:
    """Sort rows; coerce cells to str; None -> ''."""
    if rows is None:
        return None
    return sorted(tuple("" if c is None else str(c) for c in row) for row in rows)


def matches(gold_rows: list[tuple] | None, pred_rows: list[tuple] | None) -> bool:
    if gold_rows is None or pred_rows is None:
        return False
    return canonicalize(gold_rows) == canonicalize(pred_rows)


# ---------- Implement these (Phase 5) ----------------------------------

def eval_one(question: dict, agent_url: str) -> dict:
    """Score one question. Return a dict capturing per-iteration correctness."""
    db_id = question["db_id"]
    gold_sql = question["gold_sql"]
    query = question["question"]

    # 1. Get gold rows
    ok, gold_rows, err = run_sql(db_id, gold_sql)
    if not ok:
        raise RuntimeError(f"Gold SQL failed: {err}")

    # 2. Call agent
    payload = {"question": query, "db": db_id}
    resp = httpx.post(agent_url, json=payload, timeout=120.0)
    resp.raise_for_status()
    agent_resp = resp.json()

    # 3. Score iterations
    # The history contains nodes like {"node": "generate_sql", "sql": "..."} or {"node": "revise", "sql": "...", "issue": "..."}
    # We want to know if the SQL *at that point* was correct.
    history = agent_resp.get("history", [])
    iteration_results = []
    
    # Each entry in history that has 'sql' represents an attempt
    sql_attempts = [v for h in history for k, v in h.items() if k == "sql"]
    
    for i, sql_attempt in enumerate(sql_attempts):
        ok, pred_rows, err = run_sql(db_id, sql_attempt)
        pass_iter = matches(gold_rows, pred_rows) if ok else False
        iteration_results.append({
            "iteration": i,
            "sql": sql_attempt,
            "pass": pass_iter,
            "error": err if not ok else None
        })

    return {
        "question": query,
        "db_id": db_id,
        "gold_sql": gold_sql,
        "agent_sql": agent_resp.get("sql"),
        "iterations": iteration_results,
        "final_ok": agent_resp.get("ok", False),
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate per-question results.

    Per-iteration carry-forward: if the agent terminated at iteration j < k
    (verify said ok at j, or it hit MAX_ITERATIONS at j < k), treat the
    question's iteration-k result as identical to its iteration-j result.
    The agent stopped emitting; whatever it had at termination is what
    would have been served had we polled at iteration k.
    """
    if not results:
        return {}

    # Find the maximum number of iterations any question went through
    max_iters = 0
    for r in results:
        max_iters = max(max_iters, len(r["iterations"]))

    if max_iters == 0:
        return {"total_questions": len(results), "pass_rate_at_iteration": {}}

    pass_counts = [0] * max_iters
    
    for r in results:
        iters = r["iterations"]
        last_pass = False
        for k in range(max_iters):
            if k < len(iters):
                last_pass = iters[k]["pass"]
            # if k >= len(iters), we use last_pass (carry-forward)
            if last_pass:
                pass_counts[k] += 1

    total = len(results)
    pass_rate_at_iteration = {
        f"iter_{k}": pass_counts[k] / total for k in range(max_iters)
    }

    return {
        "total_questions": total,
        "final_pass_rate": pass_counts[-1] / total if max_iters > 0 else 0,
        "pass_rate_at_iteration": pass_rate_at_iteration,
    }


# ---------- Main (provided) --------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_FILE)
    parser.add_argument("--agent-url", default=AGENT_URL_DEFAULT)
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.eval_set.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(questions)} eval questions from {args.eval_set}")

    results: list[dict] = []
    t0 = time.monotonic()
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['db_id']}: {q['question'][:60]}...", flush=True)
        results.append(eval_one(q, args.agent_url))
    elapsed = time.monotonic() - t0

    summary = summarize(results)
    out = {
        "summary": summary,
        "wall_clock_seconds": elapsed,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
