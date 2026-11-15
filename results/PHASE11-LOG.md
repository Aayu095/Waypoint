# PHASE 11 LOG — Real agent connections, visible (2026-11-15)

## What was built

The console previously showed only runs it triggered itself through
`/api/find_tools`. The MCP server is the door a real external agent
uses — and its calls were invisible. Phase 11 closes that gap:

1. **`app/mcp_server.py` — call logging.** On every `tools/call`
   (success or tool error), one JSON line is appended to
   `results/agent-calls.jsonl`: `ts` (UTC ISO), `tool`, a compact args
   summary, and a compact result summary — for `find_tools`: chain,
   tokens, `refused` + `blocked_tool`/`missing_scope` when refused;
   for `resolve_entity`: resolved name/kind/ref; for
   `report_outcome`: success flag + edges reweighted. Logging is
   wrapped in try/except and can never break the server or change a
   response (tool behavior and response shapes untouched).
2. **`app/server.py` — `GET /api/agent_feed`.** Returns the last 20
   JSONL entries, newest first; `[]` when the file doesn't exist.
   No other route changed.
3. **`app/demo.html` — LIVE AGENT FEED panel** at the bottom of the
   RUN view, in the console's visual language (dark panels, 1px
   borders, mono labels, orange sparingly). Polls `/api/agent_feed`
   every 4s, shows up to 5 recent external calls (time, meta-tool,
   chain or refusal, tokens). Empty state is one honest line:
   "No external agent calls yet — connect an agent via MCP to see it
   work here." No entries are ever faked.
4. **`app/prove_mcp.py`** gained the t04 refusal call (support_agent →
   REFUSED at void_invoice / payments:admin) so the canonical proof
   driver exercises it; README's console paragraph now documents the
   feed.

## Proof (external client, not the console)

`python3 app/prove_mcp.py` — a separate stdio process speaking
JSON-RPC to the MCP server: initialize, tools/list, find_tools (t03
shape), resolve_entity, find_tools (t04 shape, refusal), report_outcome.
**ALL PASS** (transcript: `results/mcp-server-proof.txt`). The four
calls landed in `results/agent-calls.jsonl` with correct fields, and
`GET /api/agent_feed` returned them newest-first. Screenshot
`results/shots/waypoint-product-agentfeed.png` (read and confirmed by
the builder) shows the feed populated with exactly those calls:
report_outcome ✓ success · 5 edges reweighted / find_tools ✕ REFUSED
at void_invoice, missing payments:admin / resolve_entity Acme Corp →
CustomerRef / find_tools full 6-tool chain · 494 tok.

## Regression gate — all match the Phase 10 verified state

- `app/run_phase2.py`: chain accuracy **20/20** (set + exact order),
  refusals **3/3**, avg tokens **253.7**, methods 13 MSpaths /
  7 resolver. Identical to Phase 3.
- App API: t03 → exact 6-tool chain, **494 tokens**; t04 as
  support_agent → refused, blocked `void_invoice`, missing
  `payments:admin`.
- Graph: **352 tools** (329 catalog + 23 ingested).

## ⚠️ Pre-existing breakage found and fixed: writes on the aged store

The first proof run exposed a failure that **predates Phase 11**:
`report_outcome`'s writes returned HTTP 500 from HydraDB, and
`run_phase2.py` failed at its weight-reset write. Diagnosis:

- Node log (`~/workspace/hydradb-run/sgk-local/node.log`):
  `object store error: Operation 'put_opts' with mode
  'PutMode::Update' not yet implemented by LocalFileSystem` —
  slatedb (the engine's pinned storage layer) needs update-mode puts
  against the aged store; this build's local object store doesn't
  implement them. Reads were unaffected; **every** write (CREATE,
  SET, DELETE, MERGE) failed on that store.
- A node restart (same `start-node.sh`, same store) did not cure it.
  Writes on a *fresh* store work (Phase 10's cold-start seed/ingest
  proved it the same morning). The last verified write on the aged
  store was Phase 7's MCP proof; every verification after the
  subsequent node restarts was read-only, so the breakage went
  unnoticed until this phase's gate re-ran a write.

Fix applied (ops-level, no engine or app-logic changes): the graph
content was rebuilt into a fresh store directory with the project's
own deterministic pipeline — `app/seed.py` (SEED VERIFY: PASS, 329
tools) + `app/ingest.py examples/real-mcp` (→ 352 tools, 23 ingested,
identical counts; entity ids also reproduce, e.g. Acme Corp id 302).
The aged store is preserved untouched at
`~/workspace/hydradb-run/sgk-local/store-aged-20261115` (rollback =
stop node, rename it back to `store`, restart). What does not carry
over: accumulated CO_USED_WITH outcome weights (they restart from the
seed state). Nothing verified depends on them — production
`find_tools` routing does not read those weights (Phase 3.5),
`run_phase2` resets them before measuring, and the benchmark /
learning numbers live in frozen results JSONs.

**Operational caveat for the freeze:** a node restart on an aged
store is the suspected trigger for the write failure. Do not restart
the HydraDB node before the demo/submission unless forced; if a
restart happens, re-verify `report_outcome` (via
`python3 app/prove_mcp.py`) immediately after.

## State left running

- HydraDB node (fresh store, pid in
  `~/workspace/hydradb-run/sgk-local/node.pid`), health `ok`.
- App server on :8077 (website `/`, console `/console`,
  `/api/agent_feed` live).
- `results/agent-calls.jsonl` contains the 4 proof calls, so the
  feed is populated for the demo; any real agent connecting via MCP
  appends to it live.
