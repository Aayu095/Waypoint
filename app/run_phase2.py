"""Phase 2 proof: find_tools against all 20 benchmark tasks.

For every task: find_tools(start, goal, task.role, entity) and compare with
the ground-truth chain in tasks.py (set equality is the pass bar; exact
order is also recorded). Then the 3 governance refusal cases: t04 run as
support_agent, t07 as dev_agent, t13 as finance_agent must all be REFUSED
with the right missing scope.

Also exercises report_outcome once per successful chain (the learning
write-back). CO_USED_WITH weights are reset to 0 first so the recorded
weights reflect exactly this run.

Results -> ~/workspace/waypoint/results/phase2.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import run  # noqa: E402
from meta_tools import find_tools, report_outcome  # noqa: E402
from tasks import TASKS  # noqa: E402

RESULTS = Path(__file__).parent.parent / "results" / "phase2.json"
TOOLS_JSON = Path(__file__).parent.parent / "data" / "tools.json"

# task id -> (role that must be refused, expected missing scope)
REFUSAL_CASES = {
    "t04": ("support_agent", "payments:admin"),
    "t07": ("dev_agent", "github:admin"),
    "t13": ("finance_agent", "misc:admin"),
}


def reset_outcome_weights():
    rows = run("MATCH (a:Tool)-[r:CO_USED_WITH]->(b:Tool) "
               "RETURN a.id AS a, b.id AS b")
    for r in rows:
        run("MATCH (a {id: $a})-[r:CO_USED_WITH]->(b {id: $b}) "
            "SET r.weight = $w", {"a": r["a"], "b": r["b"], "w": 0})
    return len(rows)


def main():
    preload = sum(t["tokens"] for t in json.loads(TOOLS_JSON.read_text()))
    reset_n = reset_outcome_weights()

    per_task = []
    exact = 0
    set_match = 0
    for task in TASKS:
        res = find_tools(task["start"], task["goal"], task["role"],
                         entity_name=task["entity"])
        got = res.get("chain") or []
        is_exact = got == task["chain"]
        is_set = sorted(got) == sorted(task["chain"])
        exact += is_exact
        set_match += is_set
        outcome = None
        if not res.get("refused") and got:
            outcome = report_outcome(got, True)
        per_task.append({
            "id": task["id"], "role": task["role"],
            "start": task["start"], "goal": task["goal"],
            "expected_chain": task["chain"], "chain": got,
            "exact_order": is_exact, "set_match": is_set,
            "refused": bool(res.get("refused")),
            "method": res.get("method"),
            "tokens_loaded": res.get("tokens_loaded"),
            "round_trips": res.get("round_trips"),
            "supplied_inputs": res.get("supplied_inputs", []),
            "report_outcome": outcome,
        })
        status = "EXACT" if is_exact else ("SET-OK" if is_set else "MISS")
        print(f"{task['id']} [{status}] method={res.get('method')} "
              f"tokens={res.get('tokens_loaded')} rt={res.get('round_trips')} "
              f"chain={got}")

    refusals = []
    refusals_ok = 0
    for task in TASKS:
        if task["id"] not in REFUSAL_CASES:
            continue
        bad_role, want_scope = REFUSAL_CASES[task["id"]]
        res = find_tools(task["start"], task["goal"], bad_role,
                         entity_name=task["entity"])
        ok = (res.get("refused") is True
              and res.get("missing_scope") == want_scope)
        refusals_ok += ok
        refusals.append({
            "id": task["id"], "run_as": bad_role,
            "expected_missing_scope": want_scope,
            "refused": bool(res.get("refused")),
            "blocked_tool": res.get("blocked_tool"),
            "missing_scope": res.get("missing_scope"),
            "correct": ok,
        })
        print(f"REFUSAL {task['id']} as {bad_role}: refused={res.get('refused')} "
              f"blocked={res.get('blocked_tool')} scope={res.get('missing_scope')} "
              f"-> {'OK' if ok else 'WRONG'}")

    done = [p for p in per_task if p["tokens_loaded"] is not None]
    avg_tokens = sum(p["tokens_loaded"] for p in done) / len(done)
    avg_rt = sum(p["round_trips"] for p in per_task) / len(per_task)
    summary = {
        "tasks": len(TASKS),
        "chain_accuracy_set": f"{set_match}/{len(TASKS)}",
        "chain_accuracy_exact_order": f"{exact}/{len(TASKS)}",
        "refusals": f"{refusals_ok}/{len(REFUSAL_CASES)}",
        "avg_tokens_loaded": round(avg_tokens, 1),
        "preload_tokens_all_329": preload,
        "token_saving_pct": round(100 * (1 - avg_tokens / preload), 2),
        "avg_round_trips": round(avg_rt, 2),
        "methods": {m: sum(1 for p in per_task if p["method"] == m)
                    for m in ("mspaths", "resolver")},
        "outcome_weights_reset": reset_n,
    }
    print("\n=== PHASE 2 SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")

    RESULTS.write_text(json.dumps(
        {"summary": summary, "tasks": per_task, "refusals": refusals},
        indent=1))
    print(f"\nwrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
