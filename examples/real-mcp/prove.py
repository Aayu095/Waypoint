"""Phase 7 proof: ingest the real MCP catalogs, then route real tasks.

Run:  python3 examples/real-mcp/prove.py

1. Counts the live graph, ingests filesystem.json + memory.json via
   app/ingest.py (the REAL ingestion run), counts again.
2. Ingests a second time — idempotency check (must add nothing).
3. Runs the tasks in tasks.json (plus its refusal case) through
   meta_tools.find_tools against the live graph.
Writes everything to results/ingest-real.json.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
APP = HERE.parent.parent / "app"
sys.path.insert(0, str(APP))

import ingest  # noqa: E402
from meta_tools import find_tools  # noqa: E402

RESULTS = HERE.parent.parent / "results" / "ingest-real.json"


def main():
    before = ingest.graph_counts()
    summary = ingest.ingest(ingest.load_specs(HERE))
    after = ingest.graph_counts()

    again = ingest.ingest(ingest.load_specs(HERE))
    after_again = ingest.graph_counts()
    idempotent = (after == after_again and again["new_tools"] == 0)

    spec = json.loads((HERE / "tasks.json").read_text())
    task_results = []
    for t in spec["tasks"]:
        res = find_tools(t["start"], t["goal"], t["role"])
        task_results.append({"id": t["id"], "text": t["text"],
                             "start": t["start"], "goal": t["goal"],
                             "role": t["role"], **res})
        print(f"{t['id']}: refused={res.get('refused')} "
              f"chain={res.get('chain')} tokens={res.get('tokens_loaded')} "
              f"method={res.get('method')}")

    ref = spec["refusal"]
    base = next(t for t in spec["tasks"] if t["id"] == ref["task"])
    rres = find_tools(base["start"], base["goal"], ref["run_as"])
    refusal = {"task": ref["task"], "run_as": ref["run_as"],
               "expected_blocked_tool": ref["expected_blocked_tool"],
               "expected_missing_scope": ref["expected_missing_scope"],
               **rres,
               "correct": bool(rres.get("refused"))
               and rres.get("blocked_tool") == ref["expected_blocked_tool"]
               and rres.get("missing_scope") == ref["expected_missing_scope"]}
    print(f"refusal {ref['task']} as {ref['run_as']}: "
          f"refused={rres.get('refused')} blocked={rres.get('blocked_tool')} "
          f"scope={rres.get('missing_scope')} -> "
          f"{'OK' if refusal['correct'] else 'WRONG'}")

    out = {
        "ingestion": summary,
        "graph_counts_before": before,
        "graph_counts_after": after,
        "idempotency": {"second_run_new_tools": again["new_tools"],
                        "counts_unchanged": after == after_again,
                        "pass": idempotent},
        "tasks": task_results,
        "refusal": refusal,
    }
    RESULTS.write_text(json.dumps(out, indent=1))
    print(f"idempotent: {idempotent}")
    print(f"wrote {RESULTS}")
    return 0 if idempotent else 1


if __name__ == "__main__":
    raise SystemExit(main())
