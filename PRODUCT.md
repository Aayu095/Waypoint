# WAYPOINT — Product Sheet

**Agents pull only what the task needs.**

## What it is

Waypoint is the tool-routing layer between your agent and your MCP tool
catalog. Instead of loading every tool definition into the model's
context on every task, your agent holds **three meta-tools** and asks
Waypoint for the exact chain a task needs — resolved live from a graph
of your tools, their typed inputs/outputs, and the permission scope each
tool requires, stored in HydraDB.

## Who buys it

Teams shipping agents against many MCP servers, and agent platforms
whose users connect more tool servers every month. The more tools a
deployment offers, the more every task costs — in tokens, in wrong-tool
calls, and in governance risk. Waypoint's buyer is whoever pays that
bill: platform teams, applied-AI teams, and enterprises governing agent
access to internal tools.

## The problem, in buyer language

- **You pay for your whole catalog on every task.** Preloading 329 tool
  definitions costs ~27,000 tokens per task before any work happens.
  Scale the catalog and the tax scales with it.
- **Retrieval finds lookalikes, not chains.** Top-k similarity returns
  the tool that *sounds* like the goal and misses the prerequisites that
  make it callable. On our 20-task benchmark it assembled the complete
  chain only 8 times in 20.
- **Every visible tool is attack surface.** If the agent can see a tool,
  a prompt injection can aim it. Visibility should be earned per task
  and per role — not granted by stuffing the context window.

## What ships

- **Waypoint MCP server** (`app/mcp_server.py`) — a stdlib-only stdio
  MCP server exposing `find_tools`, `resolve_entity`, and
  `report_outcome`. Add it to any MCP client's config; your agent is
  routing through the graph in minutes.
- **Ingestion CLI** (`app/ingest.py`) — point it at any MCP `tools/list`
  export (file or directory) and your real catalog becomes graph:
  tools, schema-derived data types, scopes, servers. Idempotent —
  re-running adds nothing.
- **Inspector console** (`app/server.py`) — a live view of the graph,
  the chains it resolves, the permission checkpoints it enforces, and
  the benchmark evidence.
- **Self-hosted on HydraDB** (open-source graph DB). Your catalog, your
  infrastructure, no per-seat cloud lock-in for the routing layer.

## Install — a customer is live the same day

```bash
# 1. Prepare the machine (one-time: packages, Rust, built HydraDB):
./setup.sh
# 2. Start everything — node, demo catalog + the real filesystem and
#    memory MCP catalogs loaded, website + console serving:
./run.sh
# -> http://localhost:8077 (website) · http://localhost:8077/console (product)
# Your own catalog, any time after:
python3 app/ingest.py path/to/your-tools.json
# Serve Waypoint to your agent:
python3 app/mcp_server.py
```

The scripted path is the tested one (cold-proven from an empty store —
`results/PHASE10-LOG.md`). A `docker-compose.yml` from the engine's
published image is included but **untested** (no Docker on the build
machine).

Verified with real catalogs: the official MCP filesystem (14 tools) and
memory (9 tools) reference servers are ingested and routed in this repo,
including a permission refusal on real tools
(`results/ingest-real.json`), and the MCP server is proven end-to-end
over stdio JSON-RPC (`results/mcp-server-proof.txt`).

## Why it wins (measured, not claimed)

- **20/20** exact tool chains on the benchmark vs **8/20** for top-k
  retrieval — at **254 tokens/task** vs 27,000 preload and 823 retrieval.
- **Governance inside traversal:** scopes are edges in the graph, so an
  agent only ever discovers tools its role may call. Under-scoped runs
  are refused, naming the blocked tool and the missing scope (3/3).
- **It learns:** outcome write-back reweights the graph; routing
  accuracy rose 0.85 → 0.90 → 0.95 → 0.95 over four passes.
- **It holds up:** after a snapshot-cache fix, 50 concurrent agents made
  150 calls with **0 errors** (before: 126 errors) on a single node.

Full evidence: `README.md`, `results/benchmark.json`,
`results/learning2.json`, `results/loadtest2.json`.

## Pricing

- **Usage:** priced per million tool resolutions — customers pay for
  the lookup and keep the ~26,700 preload tokens per task it replaces.
- **Governance tier:** per-seat pricing for role-scoped traversal,
  refusal audit, and scope management — the enterprise feature, sold
  as such.

## Honest limits

- **Single-node HydraDB.** All load numbers come from one node on a
  shared 1.5-vCPU VM; production figures need a dedicated box, and
  nothing above 50 concurrent agents has been tested.
- **The benchmark catalog is synthetic by design** — ground-truth chains
  require a catalog with known type contracts. Real catalogs arrive via
  ingestion; the 23 real tools above are the verified sample, not a
  benchmark.
- **Token counts are definition-size estimates** from the catalog, not
  a specific vendor tokenizer's output.
- **Traversal quality follows schema quality.** Chains are only as good
  as the types your tools declare; loosely-typed servers route
  shallowly.
- HydraDB is under the Elastic License 2.0; Waypoint is an application
  on top of it, not a managed HydraDB offering.
