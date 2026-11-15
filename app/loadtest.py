"""Waypoint load test: 50 concurrent simulated agents x 3 rounds.

Each agent thread runs meta_tools.find_tools() against the LIVE HydraDB
server, rotating over the 20 benchmark tasks (each with its stated role
from tasks.py). 150 calls total. We report wall time, throughput, and
per-call latency (mean / p50 / p95 / max, nearest-rank) plus every error
verbatim — honest numbers on a shared VM, no cherry-picking.

CO_USED_WITH weights are reset to 0 before and after the run (same
reset as run_phase2.reset_outcome_weights) so later demos start clean.
find_tools itself never writes weights (only report_outcome does), so
the reset is belt-and-braces state hygiene.

Results -> ~/workspace/waypoint/results/loadtest.json
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

RESULTS = Path(__file__).parent.parent / "results" / "loadtest.json"

AGENTS = 50
ROUNDS = 3


def _nearest_rank(sorted_vals, pct):
    import math
    k = max(1, math.ceil(pct / 100 * len(sorted_vals)))
    return sorted_vals[k - 1]


def main():
    reset_before = reset_outcome_weights()
    print(f"weights reset before: {reset_before} edges")

    results = []          # per-call dicts
    lock = threading.Lock()

    def agent(agent_id):
        for rnd in range(ROUNDS):
            # rotating mix: call number n -> task n % 20
            n = agent_id * ROUNDS + rnd
            task = TASKS[n % len(TASKS)]
            rec = {"agent": agent_id, "round": rnd + 1,
                   "task": task["id"], "role": task["role"]}
            t0 = time.perf_counter()
            try:
                res = find_tools(task["start"], task["goal"], task["role"],
                                 entity_name=task["entity"])
                rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
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
    with ThreadPoolExecutor(max_workers=AGENTS) as ex:
        list(ex.map(agent, range(AGENTS)))
    wall = time.perf_counter() - t_start

    reset_after = reset_outcome_weights()
    print(f"weights reset after: {reset_after} edges")

    total = len(results)
    errors = [r for r in results if "error" in r]
    lats = sorted(r["latency_ms"] for r in results)
    summary = {
        "agents_concurrent": AGENTS,
        "rounds_per_agent": ROUNDS,
        "total_calls": total,
        "errors": len(errors),
        "error_strings": sorted({r["error"] for r in errors}),
        "wall_time_s": round(wall, 2),
        "throughput_calls_per_s": round(total / wall, 3),
        "latency_ms": {
            "mean": round(sum(lats) / len(lats), 1),
            "p50": _nearest_rank(lats, 50),
            "p95": _nearest_rank(lats, 95),
            "max": lats[-1],
        },
        "weights_reset_before": reset_before,
        "weights_reset_after": reset_after,
        "note": ("50 threads on a shared VM (1.5 vCPU) against a single "
                 "HydraDB node; find_tools issues ~7 HTTP queries per call. "
                 "Numbers are as measured, no warm-up exclusion."),
    }
    RESULTS.write_text(json.dumps(
        {"summary": summary, "calls": sorted(
            results, key=lambda r: (r["agent"], r["round"]))}, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
