# WAYPOINT — Pitch

**Agents pull only what the task needs.**

## Buyer

Teams shipping agents against many MCP servers, and agent platforms whose
users connect more tool servers every month. The more tools a deployment
offers, the more every single task costs — in tokens, in wrong-tool calls,
and in governance risk.

## The pain, in numbers

Measured on our 329-tool catalog and 20 multi-step tasks
(`results/benchmark.json`):

- Preloading all tool definitions costs **27,000 tokens per task** — paid
  on every task, before any work happens.
- The standard fix, top-k retrieval, returned the **complete tool chain in
  only 8 of 20 tasks** — it finds lookalike tools, not the prerequisite
  chain that makes the goal tool callable.
- Every undiscovered-but-callable tool is also a governance hole: if the
  agent can see it, a prompt injection can aim it.

## The product

Waypoint stores the tool catalog as a graph in HydraDB — tools, typed
inputs/outputs, prerequisites, and the permission scope each tool
requires. The agent holds **three meta-tools** instead of hundreds of
definitions:

- `find_tools` traverses the graph (native `algo.MSpaths`, validated,
  with a resolver fallback for multi-input joins) and returns only the
  exact chain for the task.
- `resolve_entity` reuses entities the agent already resolved.
- `report_outcome` writes results back, reweighting the graph so routing
  improves with use.

## The race

| Arm | Chain accuracy | Tokens / task |
|---|---|---|
| Preload-all | n/a — chain always in set | 27,000 |
| TF-IDF top-10 | 8/20 full chain | 823 |
| **Waypoint graph** | **20/20 exact** | **254** |

106× fewer tokens than preload-all. 3.2× fewer than retrieval — with the
full chain, in order, prerequisites included.

## The differentiator: governance inside traversal

Permission scopes are edges in the graph (`REQUIRES_SCOPE`), so traversal
itself is the checkpoint: **an agent only ever discovers tools its role
may call.** In the benchmark, under-scoped runs were refused 3/3 — naming
the blocked tool and the missing scope, with no silent rerouting. Tool
sprawl and tool-definition injection are the same problem seen from two
sides; Waypoint answers both with the structure enterprises already pay
to govern.

## It learns

Routing accuracy over four passes of outcome feedback: **0.85 → 0.90 →
0.95 → 0.95**. (Our first mechanism honestly failed — 0.40 → 0.35 flat;
the fix was shortest-first ranking plus failure feedback, and both curves
are in the repo.)

## Pricing story

- **Usage:** priced per million tool resolutions — the customer pays for
  the lookup, and saves the ~26,700 preload tokens per task it replaces.
- **Governance tier:** per-seat pricing for role-scoped traversal, refusal
  audit, and scope management — the enterprise feature, sold as such.

## Product form

Waypoint ships as a product, not a demo: an **MCP server**
(`app/mcp_server.py`, stdio, three meta-tools) that drops into any MCP
client's config, an **ingestion CLI** (`app/ingest.py`) that turns a
customer's own `tools/list` exports into the graph, and the **inspector
console** — all self-hosted on HydraDB. A customer is live the same
day: point ingestion at their tool catalog, add the server to their
agent config, done. Proof in-repo: the official MCP filesystem and
memory reference servers are ingested and routed — including a
permission refusal on real tools (`results/ingest-real.json`) — and the
MCP server is verified end-to-end over stdio JSON-RPC
(`results/mcp-server-proof.txt`).

## The ask

Design partners shipping agents against 10+ MCP servers. Waypoint drops
in as the context layer between your agent and your tool catalog: fewer
tokens per task, chains that actually run, and a permission checkpoint
that lives in the traversal — not in a prompt asking the model to behave.
