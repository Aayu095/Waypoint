# WAYPOINT

**Agents pull only what the task needs.**

**Live website: https://waypoint-nine-iota.vercel.app** — the product site;
its "Open the product" page shows live captures of the console and how to run
it yourself.

Waypoint is a tool-routing graph for AI agents, built on HydraDB. Instead of
preloading every tool definition into the agent's context, the agent holds
three meta-tools and traverses a graph of tools, typed data, and permission
scopes to pull exactly the tool chain a task requires — nothing more.

## The problem

Agents connected to many MCP servers drown in tool definitions. In our
catalog of **329 tools**, preloading every definition costs **27,000 tokens
per task** before any work happens. The usual fix — retrieve the top-k most
similar tool definitions — fails differently: tool *chains* are multi-hop.
To email Acme Corp's invoice PDF, an agent needs `lookup_customer` →
`list_invoices` → `get_invoice` → `invoice_pdf` → `find_contact` →
`send_email`. Similarity search finds lookalikes, not chains: it retrieves
`send_email` but misses the prerequisites that make it callable.

A graph is the right shape for this — which is the only reason to use one.
Waypoint's benchmark (below) includes the cases where retrieval fails.

## Install

Waypoint is a **product, self-hosted**: a HydraDB graph plus a
stdlib-only Python app. No accounts, no cloud. A customer is live the
same day. The tested path is three steps (Ubuntu 24.04):

```bash
# 1. Prepare the machine — system packages, Rust, and a built HydraDB.
#    One-time; ~30-60 min on first run, ~10 GB disk. Every step skips
#    if already done:
./setup.sh

# 2. Start everything — HydraDB node, catalogs loaded, app serving:
./run.sh

# 3. Open it:
#    http://localhost:8077           the website
#    http://localhost:8077/console   the product
```

`setup.sh` clones HydraDB (github.com/hydra-db/hydradb) at the pinned
commit `9166374` (v0.4.0) into `../hydradb`, next to this repo — set
`HYDRA_SRC=/path/to/checkout` to use an existing clone. It builds
LAGraph from source via HydraDB's own script (Ubuntu ships no LAGraph
package) and builds the `graph-node` binary. `run.sh` starts that node
against `./data/store` (override with `WAYPOINT_STORE=/path`) on Bolt
17687 / HTTP 18443 / Admin 19091, seeds the 329-tool demo catalog,
ingests the real MCP catalogs under `examples/real-mcp/` (+23 tools:
the official filesystem and memory reference servers), and serves the
website + console on :8077. Both scripts are idempotent — re-running
changes nothing. This exact path was cold-proven from an empty store;
see `results/PHASE10-LOG.md`.

One fixed path to know about: `app/client.py` reads the node's auth
token from `~/workspace/hydradb-run/token.txt`. `run.sh` creates that
file on first run (chmod 600) and points the node at the same file.

Load your own catalog at any time, and serve Waypoint to an agent:

```bash
python3 app/ingest.py path/to/tools.json     # any MCP tools/list export,
                                             # file or directory; idempotent
python3 app/mcp_server.py                    # stdio JSON-RPC 2.0 MCP server
```

Docker: `docker-compose.yml` + `Dockerfile` are provided from the
engine's published image spec (`ghcr.io/hydra-db/hydradb:0.4.0`) but are
**UNTESTED** — Docker was unavailable on the build machine. The scripted
path above is the tested one.

## Use it from your agent

Add Waypoint to your MCP client's config — your agent then holds three
meta-tools instead of your whole catalog:

```json
{
  "mcpServers": {
    "waypoint": {
      "command": "python3",
      "args": ["app/mcp_server.py"]
    }
  }
}
```

- `find_tools(start_type, goal_type, role, entity_name?)` → the exact
  chain for the task, permission-checked against the role's scopes.
- `resolve_entity(name)` → entities already resolved in the graph.
- `report_outcome(chain, success)` → writes the outcome back; routing
  improves with use.

Proven end-to-end over stdio: `results/mcp-server-proof.txt` (driver:
`app/prove_mcp.py`). Real-catalog ingestion and routing proof:
`results/ingest-real.json`. Product sheet: `PRODUCT.md`. The inspector
console (`python3 app/server.py` → http://localhost:8077) shows the
graph, chains, and checkpoints live. External agent calls are visible
there too: the MCP server appends every `tools/call` to
`results/agent-calls.jsonl`, and the console's **LIVE AGENT FEED** (RUN
view, served from `/api/agent_feed`) shows each call as it happens —
the chain it routed, the tokens it cost, or the checkpoint that
refused it.

## How it works

The agent holds **three meta-tools** instead of 329 definitions:

1. **`find_tools(start_type, goal_type, role, entity?)`** — finds the tool
   chain from the type the agent starts with to the type the task must
   produce.
2. **`resolve_entity(name)`** — returns entities already resolved in the
   graph (e.g. "Acme Corp" → its CRM ref), skipping repeat lookups.
3. **`report_outcome(chain, success)`** — writes the outcome back,
   reweighting `CO_USED_WITH` edges between consecutive chain tools
   (+1 on success, cap +10; −1 on failure, floor −5).

**Graph schema** (seeded in HydraDB): 329 `Tool` nodes, 55 `DataType`
nodes, 25 `Scope` nodes, 12 `MCPServer` nodes, 7 `Entity` nodes. Edges:
`INPUT_TO` / `OUTPUT` (typed consumes/produces), `REQUIRES` (tool
prerequisites), `REQUIRES_SCOPE` (permission checkpoints), `HOSTED_BY`,
`IS_TYPE`, `CO_USED_WITH` (weighted, learned).

**Chain finding, two attempts:**

1. **Native `algo.MSpaths`** over the `INPUT_TO`/`OUTPUT` edges — one call,
   many sources to targets. The returned path is then **validated**: every
   tool must be a core tool and every consumed type must be produced by an
   earlier tool in the path. A single simple path cannot express multi-input
   joins (13 of 20 benchmark tasks resolve this way).
2. **Validated resolver fallback** — a cost-ordered forward search over the
   graph edges (minimising agent-supplied inputs, then chain length) for
   the join tasks MSpaths cannot express (7 of 20).

**Permission checkpoints.** Every tool's `REQUIRES_SCOPE` scopes are checked
against the calling role's scopes before a chain is returned. If a tool is
out of scope, the call is **refused** — naming the blocked tool and the
missing scope. There is no silent rerouting around a checkpoint. An agent
only ever discovers tools its role may call.

**Learning.** Outcome write-back reweights the graph's `CO_USED_WITH`
edges; a ranking layer over candidate chains (shortest first, learned
weight as tiebreak) improves with use — see the learning results below.

## Benchmark — the race

Same 329-tool catalog, same 20 multi-step tasks with known correct chains,
three ways to load tools (full data: `results/benchmark.json`):

| Arm | Chain accuracy | Tokens / task | Round trips | Latency |
|---|---|---|---|---|
| A · preload-all (329 tools) | n/a by construction — chain always in the loaded set | 27,000 | — | — |
| B · TF-IDF top-10 retrieval | **8/20** full chain (mean recall 0.40) | 823.2 | 1 retrieval | — |
| C · **Waypoint graph** | **20/20 exact** | **253.7** | 7.35 | mean 1,087.9 ms · p95 1,369.6 ms |

Waypoint loads **106× fewer tokens than preload-all** and **3.2× fewer
than TF-IDF top-10**, while finding the complete chain in 20/20 tasks vs
8/20. Permission refusals: **3/3 correct** (`void_invoice` blocked without
`payments:admin`, `merge_pr` without `github:admin`, `sign_pdf` without
`misc:admin`).

**Load test — reported honestly.** 50 concurrent simulated agents × 3
rounds = 150 `find_tools` calls against the single local node: **126 calls
errored**, every one an HTTP 408 `query_timeout` (the node's 30 s query
timeout) as queries queued behind each other; throughput 0.61 calls/s,
mean latency 70.7 s. A supplementary 5-agent run completed 15/15 calls
with 0 errors but already at 15.3 s mean latency. Single-agent latency is
~1.1 s (benchmark above). Conclusion: on this shared 1.5-vCPU VM the
single node saturates almost immediately under concurrency — the routing
logic is not the bottleneck, the box is. Full data:
`results/loadtest.json`, `results/loadtest-5agent.json`.

**Phase 5 — the fix, re-measured.** The diagnosis was the repeated
pulls, not the routing: every call re-fetched the whole catalog
(~7 queries). The catalog now loads once per process into a snapshot
(TTL 60 s, invalidated on any `report_outcome` write); the MSpaths
traversal and the entity lookup still run live against HydraDB, so a
warm call issues **2 DB queries instead of ~7** — and `find_tools` now
reports both counts (`db_queries`, `cache_hit`) next to the unchanged
logical `round_trips`. Same protocol re-run (`app/loadtest2.py`):
**10 agents — 0 errors, mean latency 1.77 s; 25 agents — 0 errors,
0.50 s; 50 agents — 0 errors in 150 calls, mean 1.23 s, p95 2.26 s,
wall 4.5 s** (vs 246 s and 126 errors before). One honest caveat: the
levels ran in a single process in 10 → 25 → 50 order, so the 50-agent
run started with a warm cache, like a long-lived server — a cold-cache
50-agent burst is untested, and nothing above 50 agents was tested.
Full data: `results/loadtest2.json`, `results/PHASE5-LOG.md`.

## Learning — v1 failed, v2 fixed it

v1 ranked candidate chains by learned edge weight first, with success-only
feedback. It **did not learn**: accuracy went 0.40 → 0.35 → 0.35 → 0.35,
because long detour chains harvested shared edge weights from other tasks
and captured the top rank, and a failing route lost nothing. v2 changed
exactly two things — rank shortest-first with weight as tiebreak only, and
decrement weights on failure — and the curve rose in a single run with no
parameter search: **0.85 → 0.90 → 0.95 → 0.95**. The one holdout (t03) is
an ordering ambiguity: the same tool set in a different, also type-valid
order, counted wrong by exact-order scoring and reported as-is.
(`results/learning.json`, `results/learning2.json`, `results/PHASE3-LOG.md`)

## Run it

```bash
# Machine prep (once) + start everything — node, catalogs, app:
./setup.sh
./run.sh
# -> http://localhost:8077 (website) · http://localhost:8077/console (product)

# Benchmarks / experiments
python3 app/run_phase2.py     # chain accuracy + refusals
python3 app/benchmark.py      # three-arm race -> results/benchmark.json
python3 app/loadtest.py       # 50-agent load test -> results/loadtest.json
python3 app/loadtest2.py      # Phase 5 re-test, 10/25/50 agents with the snapshot cache -> results/loadtest2.json
```

The demo page runs tasks **live** against the graph: pick a task, pick a
role, and watch the chain resolve — or run t04 as `support_agent` and hit
the permission checkpoint.

## Honest limitations

- **Arm B is a lexical baseline, not a neural embedding model.** TF-IDF
  cosine in pure Python (scikit-learn is not installed on this VM). A
  strong embedding retriever would score better than 8/20; it would still
  face the structural problem — top-k returns a set, not an ordered,
  type-valid chain with prerequisites — but the exact gap would narrow.
- **Token counts are definition-size estimates** computed from the tool
  catalog, not a specific vendor tokenizer's output.
- **Latency was measured on a shared VM** (1.5 vCPU) against a single
  HydraDB node. The Phase 4 load test showed that node saturating under
  concurrency; the Phase 5 snapshot cache removed the repeated-pull
  bottleneck (0 errors at 50 concurrent agents on the same box), but
  every number here is still from a shared VM — production numbers need
  a dedicated box.
- **The catalog is synthetic but typed**: 41 hand-authored core tools with
  real consume/produce type contracts and REQUIRES prerequisites, plus
  288 generated distractor tools. The chains, traps, and ground truth are
  by construction from those type contracts.
- HydraDB is under the Elastic License 2.0; Waypoint is an application on
  top of it, not a managed HydraDB offering.
