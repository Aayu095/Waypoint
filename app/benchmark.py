"""Phase 3 benchmark: three retrieval arms over the same 20 tasks.

ARM A — preload-all (the naive agent baseline):
  Every tool definition is loaded into context for every task.
  tokens_per_task = sum of ALL tools' token costs in tools.json
  (recomputed here, never hardcoded). Retrieved set = all tools, so the
  ground-truth chain is contained by construction; chain accuracy is
  reported as "n/a-by-construction". The honest preload story is cost.

ARM B — vector top-k (lexical stand-in):
  TF-IDF cosine similarity between the task text and each tool's
  "key + description" text, top k=10. Method label: TF-IDF lexical
  retrieval, pure Python (sklearn is not installed on this VM) — an
  honest lexical baseline, NOT a neural embedding model. Per task:
  retrieved set, whether the FULL ground-truth chain is a subset of the
  retrieved set (chain_recall), and the token cost of the retrieved set.

ARM C — graph (Waypoint find_tools):
  The real meta_tools.find_tools against the live HydraDB graph, run
  with each task's own role and entity. Records chain exact-match,
  tokens_loaded, round_trips, and wall-clock latency per call.

Every number in results/benchmark.json comes from these actual runs.
"""

import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from meta_tools import find_tools  # noqa: E402
from tasks import TASKS  # noqa: E402

APP = Path(__file__).parent
TOOLS_JSON = APP.parent / "data" / "tools.json"
RESULTS = APP.parent / "results" / "benchmark.json"
K = 10


# --------------------------------------------------------------------------
# Arm B: TF-IDF cosine (pure Python)
# --------------------------------------------------------------------------

def _terms(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def tfidf_topk(tools, query_text, k):
    docs = [_terms(t["key"].replace("_", " ") + " " + t["desc"])
            for t in tools]
    n = len(docs)
    df = Counter()
    for d in docs:
        df.update(set(d))
    idf = {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}

    def vec(terms):
        tf = Counter(terms)
        v = {w: c * idf.get(w, math.log(n + 1) + 1.0) for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}

    doc_vecs = [vec(d) for d in docs]
    qv = vec(_terms(query_text))
    scored = []
    for tool, dv in zip(tools, doc_vecs):
        score = sum(qv.get(w, 0.0) * x for w, x in dv.items())
        scored.append((score, tool))
    scored.sort(key=lambda s: (-s[0], s[1]["key"]))
    return [t for _s, t in scored[:k]]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def p95(values):
    """95th percentile, nearest-rank method."""
    s = sorted(values)
    idx = max(0, math.ceil(0.95 * len(s)) - 1)
    return s[idx]


def main():
    tools = json.loads(TOOLS_JSON.read_text())
    by_key = {t["key"]: t for t in tools}
    preload_tokens = sum(t["tokens"] for t in tools)

    # ---- ARM A: preload-all
    arm_a = {
        "name": "preload-all",
        "tools_loaded_per_task": len(tools),
        "tokens_per_task": preload_tokens,
        "chain_accuracy": "n/a-by-construction",
        "note": "retrieved set = all tools, chain always contained; "
                "the preload cost is the story",
    }

    # ---- ARM B: TF-IDF top-k
    b_rows = []
    for task in TASKS:
        retrieved = tfidf_topk(tools, task["text"], K)
        keys = [t["key"] for t in retrieved]
        recall = set(task["chain"]).issubset(set(keys))
        b_rows.append({
            "id": task["id"],
            "retrieved": keys,
            "chain_recall": recall,
            "chain_found": sorted(set(task["chain"]) & set(keys)),
            "chain_missing": sorted(set(task["chain"]) - set(keys)),
            "tokens": sum(t["tokens"] for t in retrieved),
        })
    arm_b = {
        "name": "vector-top-k",
        "method": "TF-IDF cosine over tool key+description vs task text "
                  "(pure Python lexical retrieval; sklearn not installed; "
                  "NOT a neural embedding model)",
        "k": K,
        "mean_chain_recall": round(
            sum(r["chain_recall"] for r in b_rows) / len(b_rows), 3),
        "tasks_with_full_chain": sum(r["chain_recall"] for r in b_rows),
        "mean_tokens": round(
            sum(r["tokens"] for r in b_rows) / len(b_rows), 1),
        "tasks": b_rows,
    }

    # ---- ARM C: graph (Waypoint)
    c_rows = []
    for task in TASKS:
        t0 = time.perf_counter()
        res = find_tools(task["start"], task["goal"], task["role"],
                         entity_name=task["entity"])
        latency_ms = (time.perf_counter() - t0) * 1000.0
        got = res.get("chain") or []
        c_rows.append({
            "id": task["id"],
            "chain": got,
            "exact_match": got == task["chain"],
            "refused": bool(res.get("refused")),
            "tokens_loaded": res.get("tokens_loaded"),
            "round_trips": res.get("round_trips"),
            "latency_ms": round(latency_ms, 1),
            "method": res.get("method"),
        })
    lat = [r["latency_ms"] for r in c_rows]
    arm_c = {
        "name": "graph-waypoint",
        "chain_accuracy_exact": sum(r["exact_match"] for r in c_rows),
        "tasks": len(c_rows),
        "mean_tokens": round(
            sum(r["tokens_loaded"] for r in c_rows) / len(c_rows), 1),
        "mean_round_trips": round(
            sum(r["round_trips"] for r in c_rows) / len(c_rows), 2),
        "mean_latency_ms": round(sum(lat) / len(lat), 1),
        "p95_latency_ms": round(p95(lat), 1),
        "per_task": c_rows,
    }

    out = {"arm_a_preload": arm_a, "arm_b_vector_topk": arm_b,
           "arm_c_graph": arm_c}
    RESULTS.write_text(json.dumps(out, indent=1))

    print(f"{'arm':<16}{'chain acc':<22}{'tokens/task':<14}"
          f"{'round trips':<13}{'latency ms (mean/p95)'}")
    print(f"{'A preload-all':<16}{'n/a-by-constr.':<22}"
          f"{arm_a['tokens_per_task']:<14}{'-':<13}-")
    print(f"{'B tfidf top-10':<16}"
          f"{arm_b['tasks_with_full_chain']}/20 full-chain"
          f"{'':<5}{arm_b['mean_tokens']:<14}{'-':<13}-")
    print(f"{'C graph':<16}"
          f"{arm_c['chain_accuracy_exact']}/20 exact"
          f"{'':<8}{arm_c['mean_tokens']:<14}"
          f"{arm_c['mean_round_trips']:<13}"
          f"{arm_c['mean_latency_ms']} / {arm_c['p95_latency_ms']}")
    print(f"\nwrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
