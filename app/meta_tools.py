"""Waypoint meta-tools: find_tools / resolve_entity / report_outcome.

The agent holds only these three tools instead of all 329 tool definitions.
All state lives in HydraDB; every function reads/writes the graph through
client.run() and counts the HTTP queries it issues (round_trips).

find_tools(start_type, goal_type, role, entity_name=None):
  1. Tries the native algo.MSpaths over INPUT_TO/OUTPUT first. The returned
     path is VALIDATED: every tool must be a core tool and every consumed
     type of every path tool must be produced by an earlier path tool (or
     be the start type). A single simple path cannot express multi-input
     joins (send_email needs EmailAddr AND InvoicePdf from two branches),
     so join tasks fail validation by design.
  2. Fallback: cost-ordered forward search over the graph edges pulled
     via Cypher. Rules (general, no task-specific logic):
       - chain tools come from the CORE catalog (catalog.py defines the
         core graph as the chain-bearing layer; distractors are retrieval
         noise that also bloats the preload baseline);
       - the pure closure C = types producible from the start type via
         core tools; a consumed type outside C may be agent-supplied
         (a name, authored text) and is recorded in `supplied_inputs`;
       - a resolved entity's ref type joins the starting set only when it
         is outside C (it fills gaps, never shortcuts a real chain);
       - search minimises (supplied inputs used, chain length);
       - REQUIRES prerequisites are expanded in dependency order.
  3. Permission checkpoint: every chain tool's REQUIRES_SCOPE scopes must
     be a subset of the role's scopes, else the call is REFUSED naming the
     blocked tool and the missing scope. No silent rerouting.

Phase 5 — snapshot cache: the five bulk metadata pulls (tools, inputs,
outputs, requires, scopes) are served from a per-process snapshot of the
catalog (TTL 60 s, invalidated immediately by any report_outcome write in
the same process). The native algo.MSpaths traversal and the
resolve_entity point lookup still hit HydraDB live on every call — only
the bulk metadata is cached. find_tools returns therefore carry three
counts: `round_trips` (logical round trips, counted exactly as the
uncached algorithm counted them, so Phase 2/3 numbers stay comparable),
`db_queries` (actual HTTP queries this call issued) and `cache_hit`
(True when the snapshot was already warm and cost 0 queries).

Phase 7 — tiered routing: the chain search runs in two passes. Tier 1 is
the curated catalog (core tools that were not ingested: the seeded
benchmark catalog); tier 2 widens to every chain-bearing tool, adding
customer catalogs ingested via app/ingest.py (Tool.source='ingested').
A chain found in tier 1 is final — including a permission REFUSAL, which
never falls through to tier 2 (no silent rerouting). Tier 2 is only
consulted when the curated catalog has no chain at all. Rationale:
curated-first is the product's priority order, and it keeps resolution
over the shipped catalog deterministic as customer catalogs grow —
Phase 7 ingestion exposed a latent tie in t20 (two type-valid,
equal-cost chains: via summarize_doc/Summary vs via get_file/
InvoicePdf) whose winner had previously been decided by search-heap
order; with the wider tool set in the same pass, the tie flipped.
Tiering restores the curated catalog's resolution exactly, bit for bit.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import run, run_raw, CypherError  # noqa: E402
from tasks import ROLES  # noqa: E402

MAX_PATH_EDGES = 14  # longest ground-truth chain is 6 tools = 12 edges


class _Counter:
    def __init__(self):
        self.n = 0        # logical round trips (as the uncached code counted)
        self.db = 0       # actual HTTP queries issued to HydraDB
        self.snap_db = 0  # of those, queries spent (re)loading the snapshot


# --------------------------------------------------------------------------
# resolve_entity
# --------------------------------------------------------------------------

def resolve_entity(name, _counter=None):
    """Return the already-resolved entity dict from the graph, or None.

    One query against the Entity node + its IS_TYPE edge; this is the lookup
    that lets the agent skip a search round trip for a known entity.
    """
    rows = run(
        "MATCH (e:Entity)-[:IS_TYPE]->(d:DataType) "
        "WHERE e.name = $name "
        "RETURN e.name AS name, e.kind AS kind, e.entity_id AS entity_id, "
        "d.name AS ref",
        {"name": name},
    )
    if _counter is not None:
        _counter.n += 1
        _counter.db += 1  # entity lookup always goes to HydraDB live
    if not rows:
        return None
    r = rows[0]
    return {"name": r["name"], "id": r["entity_id"], "kind": r["kind"],
            "ref": r["ref"]}


# --------------------------------------------------------------------------
# graph pulls (used by validation + the fallback resolver)
#
# Phase 5 — snapshot cache. The catalog these five pulls describe changes
# only when someone writes to the graph, yet the uncached code re-pulled
# all five on EVERY find_tools call (~7 sequential HTTP queries per call).
# Under concurrency those repeated pulls were what queued the single node
# past its own 30 s query timeout (Phase 4: 126/150 calls errored at 50
# concurrent agents). So the five structures are loaded ONCE per process
# into a snapshot and the pulls below are served from memory.
#
# Invalidation: (a) TTL of SNAPSHOT_TTL_S seconds, (b) immediately on any
# report_outcome write in this process (the only write path here).
# The native algo.MSpaths call and resolve_entity still hit HydraDB live
# on every find_tools — only the bulk metadata is cached.
# --------------------------------------------------------------------------

SNAPSHOT_TTL_S = 60.0

_snapshot = None  # dict: loaded_at + tools/consumes/produces/requires/scopes
_snapshot_lock = threading.Lock()


def _fetch_tools(counter):
    rows = run("MATCH (t:Tool) RETURN t.key AS key, t.tokens AS tokens, "
               "t.core AS core, t.source AS source")
    counter.db += 1
    return {r["key"]: {"tokens": r["tokens"], "core": bool(r["core"]),
                       "source": r["source"]}
            for r in rows}


def _fetch_inputs(counter):
    rows = run("MATCH (d:DataType)-[:INPUT_TO]->(t:Tool) "
               "RETURN d.name AS dt, t.key AS tool")
    counter.db += 1
    consumes = {}
    for r in rows:
        consumes.setdefault(r["tool"], []).append(r["dt"])
    return consumes


def _fetch_outputs(counter):
    rows = run("MATCH (t:Tool)-[:OUTPUT]->(d:DataType) "
               "RETURN t.key AS tool, d.name AS dt")
    counter.db += 1
    produces = {}
    for r in rows:
        produces.setdefault(r["tool"], []).append(r["dt"])
    return produces


def _fetch_requires(counter):
    rows = run("MATCH (a:Tool)-[:REQUIRES]->(b:Tool) "
               "RETURN a.key AS tool, b.key AS req")
    counter.db += 1
    requires = {}
    for r in rows:
        requires.setdefault(r["tool"], []).append(r["req"])
    return requires


def _fetch_scopes(counter):
    rows = run("MATCH (t:Tool)-[:REQUIRES_SCOPE]->(s:Scope) "
               "RETURN t.key AS tool, s.name AS scope")
    counter.db += 1
    scopes = {}
    for r in rows:
        scopes.setdefault(r["tool"], []).append(r["scope"])
    return scopes


def _snapshot_fresh():
    return (_snapshot is not None
            and time.monotonic() - _snapshot["loaded_at"] < SNAPSHOT_TTL_S)


def _get_snapshot(counter):
    """Return the catalog snapshot, (re)loading it from HydraDB when absent
    or past TTL. The load happens under a lock with a re-check, so a burst
    of concurrent callers shares ONE load instead of stampeding the node.
    Load queries are attributed to the loading caller's counter (db +
    snap_db); callers served from a warm snapshot pay 0."""
    global _snapshot
    if _snapshot_fresh():
        return _snapshot
    with _snapshot_lock:
        if _snapshot_fresh():
            return _snapshot
        sub = _Counter()
        fresh = {
            "tools": _fetch_tools(sub),
            "consumes": _fetch_inputs(sub),
            "produces": _fetch_outputs(sub),
            "requires": _fetch_requires(sub),
            "scopes": _fetch_scopes(sub),
            "loaded_at": time.monotonic(),
        }
        counter.db += sub.db
        counter.snap_db += sub.db
        _snapshot = fresh
        return fresh


def invalidate_snapshot():
    """Drop the cached snapshot; the next pull reloads from HydraDB.
    Called after any in-process graph write (report_outcome)."""
    global _snapshot
    with _snapshot_lock:
        _snapshot = None


def _pull_tools(counter):
    counter.n += 1  # logical round trip, counted as the uncached code did
    return _get_snapshot(counter)["tools"]


def _pull_inputs(counter):
    counter.n += 1
    return _get_snapshot(counter)["consumes"]


def _pull_outputs(counter):
    counter.n += 1
    return _get_snapshot(counter)["produces"]


def _pull_requires(counter):
    counter.n += 1
    return _get_snapshot(counter)["requires"]


def _pull_scopes(counter):
    counter.n += 1
    return _get_snapshot(counter)["scopes"]


# --------------------------------------------------------------------------
# MSpaths attempt
# --------------------------------------------------------------------------

def _mspaths_chain(start_type, goal_type, counter):
    """One native MSpaths call. Returns the ordered tool keys of the
    returned path, or None if no path came back."""
    q = (
        "CALL algo.MSpaths({"
        "sourceLabel: 'DataType', sourceProperty: 'name', "
        f"sourceValues: ['{start_type}'], targetValues: ['{goal_type}'], "
        "relTypes: ['INPUT_TO', 'OUTPUT'], relDirection: 'outgoing', "
        f"maxLen: {MAX_PATH_EDGES}, pathCount: 1, pairwise: false, "
        "resultLimit: 10}) YIELD path RETURN path"
    )
    body = run_raw(q)
    counter.n += 1
    counter.db += 1  # the native traversal always runs live on HydraDB
    rows = body.get("rows", [])
    if not rows:
        return None
    path = rows[0][0].get("value") if isinstance(rows[0][0], dict) else None
    if not path:
        return None
    keys = []
    for node in path.get("nodes", []):
        if "Tool" in node.get("labels", []):
            keys.append(node["properties"]["key"]["String"])
    return keys or None


def _path_is_complete(chain, start_type, allowed, consumes, produces):
    """Validate an MSpaths path: only tools in the current tier's allowed
    set, and every consumed type of every tool produced by an earlier
    tool (or the start type)."""
    available = {start_type}
    for key in chain:
        if key not in allowed:
            return False
        if not all(c in available for c in consumes.get(key, [])):
            return False
        available |= set(produces.get(key, []))
    return True


def _expand_requires(chain, requires):
    """Insert REQUIRES prerequisites before their dependents, in
    dependency order, deduplicated."""
    ordered = []

    def add(key, seen):
        if key in ordered or key in seen:
            return
        seen = seen | {key}
        for req in requires.get(key, []):
            add(req, seen)
        if key not in ordered:
            ordered.append(key)

    for key in chain:
        add(key, set())
    return ordered


# --------------------------------------------------------------------------
# fallback resolver (backward chaining over graph edges)
# --------------------------------------------------------------------------

_EXCEEDED = object()  # sentinel: expansion budget hit


class _Resolver:
    """Cost-ordered forward search over the core tool graph.

    State = (types produced by chain tools, agent-supplied types used).
    A core tool fires when every consumed type is in base ∪ produced ∪ S,
    where base = start types (+ entity ref when it fills a gap) and
    S = types outside the pure producible closure of the start. Search
    minimises (len(supplied used), chain length) via Dijkstra.

    Phase 7 guard: when the goal is UNREACHABLE the Dijkstra must exhaust
    the state space before answering None — with supplied inputs allowed,
    that space is combinatorial and a tier-1 miss (a real-catalog task
    searched against the curated catalog first) blew up memory. So the
    search runs with an expansion budget; if the budget trips, it retries
    inside the goal cone (tools whose produced types can reach the goal
    through the type graph). Cone pruning is sound and complete for
    reachability: every tool on any chain to the goal produces a type
    the next chain tool consumes, hence a cone type, by induction.
    """

    MAX_CHAIN = 10
    EXPANSION_BUDGET = 20000

    def __init__(self, tools, consumes, produces, requires):
        self.tools = tools
        self.consumes = consumes
        self.produces = produces
        self.requires = requires
        self.core_keys = sorted(k for k in tools if tools[k]["core"])

    def producible_closure(self, start_types, keys):
        """Types reachable from start_types via the given tools
        (no supplied inputs)."""
        closure = set(start_types)
        changed = True
        while changed:
            changed = False
            for key in keys:
                if all(c in closure for c in self.consumes.get(key, [])):
                    for t in self.produces.get(key, []):
                        if t not in closure:
                            closure.add(t)
                            changed = True
        return closure

    def _goal_cone(self, goal_type):
        """Types that can lead to goal_type: the goal plus, transitively,
        every type consumed by a tool that produces a cone type."""
        cone = {goal_type}
        changed = True
        while changed:
            changed = False
            for key in self.core_keys:
                if set(self.produces.get(key, [])) & cone:
                    for t in self.consumes.get(key, []):
                        if t not in cone:
                            cone.add(t)
                            changed = True
        return cone

    def resolve(self, start_types, goal_type, entity_ref=None):
        """Return (chain, supplied_inputs) or None."""
        out = self._search(start_types, goal_type, entity_ref,
                           self.core_keys, self.EXPANSION_BUDGET)
        if out is not _EXCEEDED:
            return out
        cone = self._goal_cone(goal_type)
        keys = [k for k in self.core_keys
                if set(self.produces.get(k, [])) & cone]
        return self._search(start_types, goal_type, entity_ref,
                            keys, None)

    def _search(self, start_types, goal_type, entity_ref, keys, budget):
        base = set(start_types)
        closure = self.producible_closure(base, keys)
        if entity_ref is not None and entity_ref not in closure:
            base.add(entity_ref)  # resolved entity fills a real gap
            closure.add(entity_ref)
        if goal_type in base:
            return [], []
        all_types = {t for k in keys for t in self.consumes.get(k, [])}
        suppliable = all_types - closure

        import heapq
        start_state = (frozenset(), frozenset())
        best_cost = {start_state: (0, 0)}
        parent = {}  # state -> (prev_state, tool_key)
        pq = [((0, 0), start_state)]
        goal_state = None
        expansions = 0
        while pq:
            cost, state = heapq.heappop(pq)
            if best_cost.get(state) != cost:
                continue
            expansions += 1
            if budget is not None and expansions > budget:
                return _EXCEEDED
            produced, used = state
            available = base | set(produced)
            if goal_type in produced:
                goal_state = state
                break
            if cost[1] >= self.MAX_CHAIN:
                continue
            for key in keys:
                ins = self.consumes.get(key, [])
                if not all(c in available or c in suppliable for c in ins):
                    continue
                new_produced = produced | frozenset(
                    self.produces.get(key, []))
                if new_produced == produced:
                    continue
                new_used = used | frozenset(
                    c for c in ins
                    if c in suppliable and c not in produced
                    and c not in base)
                nstate = (new_produced, new_used)
                ncost = (len(new_used), cost[1] + 1)
                if nstate not in best_cost or ncost < best_cost[nstate]:
                    best_cost[nstate] = ncost
                    parent[nstate] = (state, key)
                    heapq.heappush(pq, (ncost, nstate))
        if goal_state is None:
            return None
        chain = []
        state = goal_state
        while state != start_state:
            prev, key = parent[state]
            chain.append(key)
            state = prev
        chain.reverse()
        return chain, sorted(goal_state[1])


# --------------------------------------------------------------------------
# find_tools
# --------------------------------------------------------------------------

def _permission_check(chain, role, scopes):
    """Return (blocked_tool, missing_scope) or None."""
    held = set(ROLES[role])
    for key in chain:
        for scope in scopes.get(key, []):
            if scope not in held:
                return key, scope
    return None


def _attempt_chain(allowed, start_type, goal_type, entity, counter,
                   tools, consumes):
    """One tier's chain search: native MSpaths (validated against the
    tier) first, then the resolver over the tier's tools only. Returns
    (chain, method, supplied) or None when the tier has no chain."""
    try:
        path = _mspaths_chain(start_type, goal_type, counter)
    except CypherError:
        path = None
    if path and _path_is_complete(path, start_type, allowed, consumes,
                                  _pull_outputs(counter)):
        requires = _pull_requires(counter)
        return _expand_requires(path, requires), "mspaths", []

    produces = _pull_outputs(counter)
    requires = _pull_requires(counter)
    sub_tools = {k: v for k, v in tools.items() if k in allowed}
    resolver = _Resolver(sub_tools, consumes, produces, requires)
    resolved = resolver.resolve(
        {start_type}, goal_type,
        entity_ref=entity["ref"] if entity is not None else None)
    if resolved is None:
        return None
    raw_chain, supplied = resolved
    return _expand_requires(raw_chain, requires), "resolver", supplied


def find_tools(start_type, goal_type, role, entity_name=None):
    counter = _Counter()

    entity = None
    if entity_name is not None:
        entity = resolve_entity(entity_name, _counter=counter)

    tools = _pull_tools(counter)
    consumes = _pull_inputs(counter)
    scopes = _pull_scopes(counter)

    # Phase 7 tiers: tier 1 = curated catalog (core, not ingested);
    # tier 2 = every chain-bearing tool (adds ingested customer tools).
    tier1 = {k for k, v in tools.items()
             if v["core"] and v.get("source") != "ingested"}
    tier2 = {k for k, v in tools.items() if v["core"]}

    # Tier skip: a chain's last tool must PRODUCE the goal type, so a
    # tier with no producer of the goal cannot hold a chain — skip its
    # search outright (read from the warm snapshot; not a counted round
    # trip). This makes the common tier-1 miss (real-catalog goals)
    # instant instead of an exhaustive no-chain search.
    produces_map = _get_snapshot(_Counter())["produces"]

    chain = None
    method = None
    supplied = []
    for allowed in (tier1, tier2):
        if goal_type != start_type and not any(
                goal_type in produces_map.get(k, [])
                for k in allowed):
            continue
        got = _attempt_chain(allowed, start_type, goal_type, entity,
                             counter, tools, consumes)
        if got is not None:
            chain, method, supplied = got
            break
    if chain is None:
        return {"refused": False, "chain": None,
                "error": f"no chain from {start_type} to {goal_type}",
                "method": "resolver", "round_trips": counter.n,
                "db_queries": counter.db,
                "cache_hit": counter.snap_db == 0}

    # --- permission checkpoint (governance gate; no silent reroute)
    blocked = _permission_check(chain, role, scopes)
    if blocked is not None:
        blocked_tool, missing_scope = blocked
        return {
            "refused": True,
            "blocked_tool": blocked_tool,
            "missing_scope": missing_scope,
            "role": role,
            "chain": chain,
            "method": method,
            "round_trips": counter.n,
            "db_queries": counter.db,
            "cache_hit": counter.snap_db == 0,
        }

    return {
        "refused": False,
        "chain": chain,
        "tokens_loaded": sum(tools[k]["tokens"] for k in chain),
        "round_trips": counter.n,
        "db_queries": counter.db,
        "cache_hit": counter.snap_db == 0,
        "method": method,
        "supplied_inputs": supplied,
        "entity": entity,
    }


# --------------------------------------------------------------------------
# report_outcome
# --------------------------------------------------------------------------

def report_outcome(chain, success):
    """Write CO_USED_WITH edges between consecutive chain tools,
    reweighting by outcome: +1 on success (cap +10), -1 on failure
    (floor -5, so a repeatedly failing route is actively avoided, not
    just unrewarded). The original plan specified "reweight edges by
    outcome" — outcome includes failure; v1 implemented only the
    success half. MERGE, read, and SET are separate statements
    (the dialect rejects MERGE+SET in one statement)."""
    counter = _Counter()
    rows = run("MATCH (t:Tool) RETURN t.key AS key, t.id AS id")
    counter.n += 1
    id_of = {r["key"]: r["id"] for r in rows}
    weights = {}
    for a, b in zip(chain, chain[1:]):
        aid, bid = id_of[a], id_of[b]
        # NOTE: MERGE must be a one-hop edge pattern; MERGE between two
        # separately MATCHed variables is rejected by the mutation engine
        # ("write query is not executable by the mutation engine").
        run("MERGE (x {id: $a})-[:CO_USED_WITH]->(y {id: $b})",
            {"a": aid, "b": bid})
        counter.n += 1
        got = run("MATCH (x {id: $a})-[r:CO_USED_WITH]->(y {id: $b}) "
                  "RETURN r.weight AS w", {"a": aid, "b": bid})
        counter.n += 1
        current = got[0]["w"] if got and got[0]["w"] is not None else 0
        new_w = max(-5, min(10, current + (1 if success else -1)))
        run("MATCH (x {id: $a})-[r:CO_USED_WITH]->(y {id: $b}) "
            "SET r.weight = $w", {"a": aid, "b": bid, "w": new_w})
        counter.n += 1
        weights[f"{a}->{b}"] = new_w
    # This process just wrote to the graph: the catalog snapshot is stale
    # by definition now, so drop it (the next find_tools reloads it).
    invalidate_snapshot()
    return {"edges": len(weights), "weights": weights,
            "round_trips": counter.n}
