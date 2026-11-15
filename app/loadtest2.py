"""Waypoint load test, Phase 5: same protocol as Phase 4, WITH the
snapshot cache, at THREE concurrency levels: 10, 25, 50 agents x 3 rounds.

Phase 4 (app/loadtest.py, uncached) saturated the single node at 50
agents: 126/150 calls errored, all HTTP 408 query_timeout, because every
find_tools call re-pulled the full catalog (~7 sequential HTTP queries).
Phase 5 serves the five bulk metadata pulls from a per-process snapshot
(meta_tools.py: TTL 60 s, invalidated on report_outcome writes); the
native algo.MSpaths traversal and the entity lookup still hit HydraDB
live on every call. This test measures whether that was the bottleneck.

Protocol is identical to Phase 4 so the numbers are comparable: agent
threads rotate over the 20 benchmark tasks with their stated roles, call
number n -> task n % 20, CO_USED_WITH weights reset before and after each
level. One process runs all three levels in sequence, so the snapshot
warms on the first calls and is shared across levels — the same way a
long-lived demo server process behaves. Per-call cache_hit / db_queries
are recorded so the warm/cold mix is visible, not hidden. Every error is
recorded verbatim and also bucketed by kind. No re-runs, no filtering.

Results -> ~/workspace/waypoint/results/loadtest2.json
"""

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from meta_tools import find_tools  # noqa: E402
from run_phase2 import reset_outcome_weights  # noqa: E402
from tasks import TASKS  # noqa: E402

RESULTS = Path(__file__).parent.parent / "results" / "loadtest2.json"

LEVELS = [10, 25, 50]
ROUNDS = 3


def _nearest_rank(sorted_vals, pct):
    import math
    k = max(1, math.ceil(pct / 100 * len(sorted_vals)))
    return sorted_vals[k - 1]


def _error_kind(err):
    if err is None:
        return None
    if "query_timeout" in err or "HTTP 408" in err:
        return "http_408_query_timeout"
    if err.startswith("unexpected refusal"):
        return "unexpected_refusal"
    return err.split(":", 1)[0]  # exception class name


def run_level(agents):
    reset_before = reset_outcome_weights()
    print(f"[{agents} agents] weights reset before: {reset_before} edges",
          flush=True)

    results = []
    lock = threading.Lock()

    def agent(agent_id):
        for rnd in range(ROUNDS):
            n = agent_id * ROUNDS + rnd
            task = TASKS[n % len(TASKS)]
            rec = {"agent": agent_id, "round": rnd + 1,
                   "task": task["id"], "role": task["role"]}
            t0 = time.perf_counter()
            try:
                res = find_tools(task["start"], task["goal"], task["role"],
                                 entity_name=task["entity"])
                rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                rec["cache_hit"] = res.get("cache_hit")
                rec["db_queries"] = res.get("db_queries")
                rec["round_trips"] = res.get("round_trips")
                if res.get("error"):
                    rec["error"] = str(res["error"])
                elif res.get("refused"):
                    rec["error"] = (f"unexpected refusal: "
                                    f"{res.get('blocked_tool')} "
                                    f"{res.get('missing_scope')}")
                else:
                    rec["chain_len"] = len(res.get("chain") or [])
                    rec["tokens_loaded"] = res.get("tokens_loaded")
                    rec["method"] = res.get("method")
            except Exception as e:  # noqa: BLE001 - record verbatim
                rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                rec["error"] = f"{type(e).__name__}: {e}"
            with lock:
                results.append(rec)

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=agents) as ex:
        list(ex.map(agent, range(agents)))
    wall = time.perf_counter() - t_start

    reset_after = reset_outcome_weights()
    print(f"[{agents} agents] weights reset after: {reset_after} edges",
          flush=True)

    total = len(results)
    errors = [r for r in results if "error" in r]
    kinds = {}
    for r in errors:
        k = _error_kind(r["error"])
        kinds[k] = kinds.get(k, 0) + 1
    lats = sorted(r["latency_ms"] for r in results)
    dbq = [r["db_queries"] for r in results if r.get("db_queries") is not None]
    hits = sum(1 for r in results if r.get("cache_hit"))
    summary = {
        "agents_concurrent": agents,
        "rounds_per_agent": ROUNDS,
        "total_calls": total,
        "errors": len(errors),
        "error_kinds": kinds,
        "error_strings": sorted({r["error"] for r in errors}),
        "wall_time_s": round(wall, 2),
        "throughput_calls_per_s": round(total / wall, 3),
        "latency_ms": {
            "mean": round(sum(lats) / len(lats), 1),
            "p50": _nearest_rank(lats, 50),
            "p95": _nearest_rank(lats, 95),
            "max": lats[-1],
        },
        "cache_hits": hits,
        "cache_hit_pct": round(100 * hits / total, 1),
        "avg_db_queries_per_call": round(sum(dbq) / len(dbq), 2) if dbq else None,
        "avg_round_trips_per_call": (
            round(sum(r["round_trips"] for r in results
                      if r.get("round_trips") is not None)
                  / max(1, sum(1 for r in results
                               if r.get("round_trips") is not None)), 2)),
        "weights_reset_before": reset_before,
        "weights_reset_after": reset_after,
    }
    print(json.dumps(summary, indent=1), flush=True)
    return {"summary": summary,
            "calls": sorted(results, key=lambda r: (r["agent"], r["round"]))}


def main():
    runs = []
    for level in LEVELS:
        runs.append(run_level(level))
    out = {
        "protocol": ("Same as Phase 4 loadtest.py (rotating 20 tasks, "
                     "stated roles, 3 rounds per agent, weights reset "
                     "around each level), one process for all levels so "
                     "the snapshot cache warms once and is shared — like "
                     "a long-lived server. Levels run 10 -> 25 -> 50 in "
                     "sequence; no level was re-run or dropped."),
        "cache": ("meta_tools snapshot: 5 bulk catalog pulls cached per "
                  "process, TTL 60 s, invalidated on report_outcome. "
                  "MSpaths + entity lookup still live per call, so a "
                  "warm call issues 2 HTTP queries instead of ~7."),
        "runs": runs,
    }
    RESULTS.write_text(json.dumps(out, indent=1))
    print(f"wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
