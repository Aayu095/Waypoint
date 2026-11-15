"""Phase 3.5 learning-curve experiment (v2).

Mechanism: report_outcome reweights CO_USED_WITH edges between
consecutive chain tools by outcome: +1 on success (cap +10), -1 on
failure (floor -5) — see meta_tools.report_outcome. v1 incremented on
success only; v1's curve did not rise (0.40 -> 0.35 -> 0.35 -> 0.35)
because weight-first ranking let long detour chains harvest shared
edges and capture the top spot, and a failing detour lost nothing.

v2 changes exactly two things, on principled grounds (both implement
what the original plan specified — "reweight edges by outcome"):
  1. RANKING: length-first (fewest tools), total CO_USED_WITH weight
     as tiebreak only (descending), then lexicographic. Shortest
     sufficient chain is the product's cost claim; weight-first
     provably lets detours capture the top (v1 diagnosis #1/#2).
  2. NEGATIVE FEEDBACK: failure decrements (implemented in
     meta_tools.report_outcome), so a captured task can escape: its
     wrong top loses weight every pass until the true chain wins.
Protocol is otherwise IDENTICAL to v1 (reset weights, 4 sequential
passes over the 20 tasks, top chain scored exact-match, feedback only
on the chain actually executed — never on the ground-truth chain) so
the v1 and v2 curves are directly comparable.

Resolver extension: enumerate ALL type-valid chains over the CORE tool
subgraph under the same admissibility rules as meta_tools._Resolver
(a tool fires when every consumed type is in base ∪ produced ∪ suppliable,
where suppliable = consumed types outside the producible closure of the
start types; a resolved entity's ref type joins the base only when it
fills a gap). Candidates are REQUIRES-expanded, deduplicated, and
permission-filtered for the task's role. Ranking, per protocol:
  (a) shorter chain first;
  (b) total CO_USED_WITH weight along the chain, descending;
  (c) lexicographic chain order (deterministic final tiebreak).

NOTE on ranking vs production find_tools: find_tools' resolver ranks by
(supplied-input count, chain length) and knows nothing of weights. This
experiment's ranking is (length, weight) BY PROTOCOL — it deliberately
does not minimise supplied inputs, so a short chain that leans on
agent-supplied types can outrank the ground-truth chain until weights
say otherwise. Per-task supplied counts of the top chain are recorded
so this effect is visible in the data.

Candidate bounds: an unbounded enumeration over supplied-input
shortcuts explodes (a first run hit the 500-candidate cap with deep
junk chains for every task — none of them permission-valid). Candidates
are therefore bounded to the resolver's own operating region: supplied
count <= the resolver-optimal supplied count for the task, and raw
chain length <= resolver-optimal length + LENGTH_SLACK (2). Within
those bounds enumeration is exhaustive.

Protocol: reset all CO_USED_WITH weights to 0; run the 20 tasks in
4 sequential passes. In each pass, for every task: pull current weights
from the graph, take the TOP-ranked candidate chain, score exact-match
vs ground truth, then report_outcome(top_chain, success=(top == truth))
— success reinforces the executed chain's edges, failure decrements
them; the ground-truth chain is never fed back (no answer-key leak).

Output: results/learning2.json with per-pass accuracy, per-task detail,
and competing-candidate counts (tasks where >1 candidate chain exists).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import run  # noqa: E402
from meta_tools import (  # noqa: E402
    _Counter, _Resolver, _expand_requires, _permission_check,
    _pull_inputs, _pull_outputs, _pull_requires, _pull_scopes,
    _pull_tools, report_outcome, resolve_entity,
)
from tasks import TASKS  # noqa: E402

RESULTS = Path(__file__).parent.parent / "results" / "learning2.json"
PASSES = 4
LENGTH_SLACK = 2    # candidates may exceed the optimal raw length by this
CANDIDATE_CAP = 500


def reset_outcome_weights():
    rows = run("MATCH (a:Tool)-[r:CO_USED_WITH]->(b:Tool) "
               "RETURN a.id AS a, b.id AS b")
    for r in rows:
        run("MATCH (a {id: $a})-[r:CO_USED_WITH]->(b {id: $b}) "
            "SET r.weight = $w", {"a": r["a"], "b": r["b"], "w": 0})
    return len(rows)


def pull_weights():
    rows = run("MATCH (a:Tool)-[r:CO_USED_WITH]->(b:Tool) "
               "RETURN a.key AS a, b.key AS b, r.weight AS w")
    return {(r["a"], r["b"]): (r["w"] or 0) for r in rows}


def enumerate_candidates(resolver, start_type, goal_type, entity_ref):
    """Type-valid core chains start->goal as {chain_tuple: supplied},
    bounded to the resolver's operating region (see module docstring)."""
    optimal = resolver.resolve({start_type}, goal_type,
                               entity_ref=entity_ref)
    if optimal is None:
        return {}
    opt_chain, opt_supplied = optimal
    max_supplied = len(opt_supplied)
    max_depth = len(opt_chain) + LENGTH_SLACK

    base = {start_type}
    closure = resolver.producible_closure(base, resolver.core_keys)
    if entity_ref is not None and entity_ref not in closure:
        base.add(entity_ref)  # resolved entity fills a real gap
        closure.add(entity_ref)
    all_types = {t for k in resolver.core_keys
                 for t in resolver.consumes.get(k, [])}
    suppliable = all_types - closure
    candidates = {}

    def dfs(chain, produced, used):
        if len(candidates) >= CANDIDATE_CAP:
            return
        if chain and goal_type in produced:
            expanded = tuple(_expand_requires(chain, resolver.requires))
            candidates.setdefault(expanded, used)
            return
        if len(chain) >= max_depth:
            return
        available = base | set(produced)
        for key in resolver.core_keys:
            if key in chain:
                continue
            ins = resolver.consumes.get(key, [])
            if not all(c in available or c in suppliable for c in ins):
                continue
            new_produced = produced | frozenset(
                resolver.produces.get(key, []))
            if new_produced == produced:
                continue
            new_used = used | frozenset(
                c for c in ins
                if c in suppliable and c not in produced and c not in base)
            if len(new_used) > max_supplied:
                continue
            dfs(chain + [key], new_produced, new_used)

    dfs([], frozenset(), frozenset())
    return candidates


def chain_weight(chain, weights):
    return sum(weights.get((a, b), 0)
               for a, b in zip(chain, chain[1:]))


def main():
    counter = _Counter()
    tools = _pull_tools(counter)
    consumes = _pull_inputs(counter)
    produces = _pull_outputs(counter)
    requires = _pull_requires(counter)
    scopes = _pull_scopes(counter)
    resolver = _Resolver(tools, consumes, produces, requires)

    reset_n = reset_outcome_weights()
    print(f"reset {reset_n} CO_USED_WITH edge weights to 0")

    passes = []
    competing_ever = set()
    for p in range(1, PASSES + 1):
        rows_out = []
        exact = 0
        competing = 0
        for task in TASKS:
            entity = resolve_entity(task["entity"])
            cands = enumerate_candidates(
                resolver, task["start"], task["goal"],
                entity["ref"] if entity else None)
            kept = {c: u for c, u in cands.items()
                    if _permission_check(list(c), task["role"],
                                         scopes) is None}
            weights = pull_weights()
            ranked = sorted(
                kept.items(),
                key=lambda item: (len(item[0]),
                                  -chain_weight(item[0], weights),
                                  item[0]))
            if len(kept) > 1:
                competing += 1
                competing_ever.add(task["id"])
            if ranked:
                top, top_supplied = ranked[0]
                top_w = chain_weight(top, weights)
                success = list(top) == task["chain"]
                report_outcome(list(top), success)
            else:
                top, top_supplied, top_w, success = None, None, None, False
            exact += success
            rows_out.append({
                "id": task["id"],
                "candidates_total": len(cands),
                "candidates_after_permission_filter": len(kept),
                "competing": len(kept) > 1,
                "top_chain": list(top) if top else None,
                "top_weight": top_w,
                "top_supplied_inputs": (sorted(top_supplied)
                                        if top_supplied is not None
                                        else None),
                "ground_truth": task["chain"],
                "exact_match": success,
            })
        acc = exact / len(TASKS)
        passes.append({
            "pass": p,
            "exact_matches": exact,
            "accuracy": acc,
            "tasks_with_competing_chains": competing,
            "tasks": rows_out,
        })
        print(f"pass {p}: accuracy {exact}/{len(TASKS)} = {acc:.2f} "
              f"(competing-chain tasks: {competing})")

    out = {
        "protocol": "reset weights; 4 sequential passes over the 20 tasks; "
                    "per task take the top-ranked candidate chain "
                    "(length asc, CO_USED_WITH weight desc, lexicographic), "
                    "score exact-match, report_outcome(top, success) with "
                    "success +1 (cap +10) / failure -1 (floor -5)",
        "ranking_note": "experiment ranking is (length, weight) per "
                        "protocol (v2; v1 was weight-first); production "
                        "find_tools ranks by (supplied-inputs, length). "
                        "Top-chain supplied inputs are recorded per task.",
        "weights_reset_edges": reset_n,
        "pass_accuracies": [pp["accuracy"] for pp in passes],
        "tasks_with_competing_chains_ever": sorted(competing_ever),
        "competing_chain_task_count_ever": len(competing_ever),
        "passes": passes,
    }
    RESULTS.write_text(json.dumps(out, indent=1))
    print(f"\nwrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
