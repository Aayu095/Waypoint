# PHASE 18 LOG — Local store rebuilt fresh AGAIN; writes work (2026-11-15)

## Why

The latest VM replacement killed the node. It was restarted via
`start-node-fresh1115.sh` on the Phase 16 store (`store-fresh-1115`) —
health ok, reads perfect (t03 chain 494, t04 refusal, resolve_entity
Acme Corp id 302) — but `python3 app/prove_mcp.py` showed
`report_outcome` → HTTP 500 again. Same proven pattern (Phases 11, 15,
16): this engine build rejects graph writes on any store that has been
through a stop/start cycle (`PutMode::Update not yet implemented by
LocalFileSystem`); only a fresh store writes. Tonight's demo video
needs the local write-back working, so the store was rebuilt fresh a
second time, following the Phase 16 recipe exactly. No code was
changed anywhere; no site/console changes; no older store was touched.

## How the node was pointed at the new store (the whole recipe)

A copied script, **`~/workspace/hydradb-run/start-node-fresh1800.sh`**,
is `start-node-fresh1115.sh` with exactly these changes: `LOCAL_PATH`
points at the new store dir
**`~/workspace/hydradb-run/sgk-local/store-fresh-1800`**, and the
pid/log/cache files are `node-fresh-1800.pid` / `node-fresh-1800.log` /
`cache-fresh-1800`. Everything else is identical: same repo binary,
same ports (Bolt 17687 / HTTP 18443 / Admin 19091), same shared token
file (`~/workspace/hydradb-run/token.txt`), same env. The wipe mode was
again deliberately NOT carried over — the script cannot delete
anything. Recovery next time = copy the script with a new store name,
run it, then `python3 app/seed.py`, then
`python3 app/ingest.py examples/real-mcp`, then start the app server,
then `python3 app/prove_mcp.py`.

## What was done

1. Stopped the old node (pid 22430, via `node-fresh-1115.pid`) and the
   app server (`fuser -k 8077/tcp`). All ports confirmed free.
2. Started the node on the fresh store via the new script — node pid
   **22580**, health `ok`.
3. `python3 app/seed.py` → **SEED VERIFY: PASS** (Tool=329; all node
   and edge counts exact).
4. `python3 app/ingest.py examples/real-mcp` → filesystem 14 new +
   memory 9 new; **tools 329 → 352 (23 ingested)**.
5. Restarted the app server against it (`nohup python3 app/server.py`,
   pid **22648**, log
   `~/workspace/hydradb-run/sgk-local/app-fresh-1800.log`).

## Verification — all on the fresh store

| Check | Result |
|---|---|
| Direct DB counts (via app/client, bypassing the app server) | **352 tools total / 23 ingested** |
| API t03 (finance_agent) | exact 6-tool chain (== expected_chain), **494 tokens_loaded**, refused=false |
| API t04 as support_agent | **refused=true**, blocked `void_invoice`, missing `payments:admin` |
| `python3 app/prove_mcp.py` | **ALL PASS** — initialize, tools/list (3 meta-tools), find_tools (494 tok), resolve_entity (Acme Corp → CustomerRef, id 302), t04 refusal, and **report_outcome: 5 edges written, weights 0 → 1 on all five** (the write that returned HTTP 500 on the restarted 1115 store) |
| `python3 app/run_phase2.py` | chains **20/20** (set + exact order), refusals **3/3**, avg 253.7 tok, token saving 99.06%, 13 MSpaths / 7 resolver — identical to the frozen Phase 3 gate; its weight-reset writes also succeeded |
| GET / and GET /console | **200 / 200** |
| GET /api/agent_feed | returns entries — newest are the proof calls, report_outcome first |

## ⚠️ Do not restart the node before the video

Both processes are left running (node **22580** on the fresh 1800
store, app **22648** on :8077). **From this moment the HydraDB node
must NOT be restarted again before tonight's demo video /
submission** — a stop/start cycle is exactly what makes this engine
build reject writes on a store. If a VM replacement kills it before
the video anyway, the recovery is this same rebuild (new store dir +
copied script + seed + ingest + prove_mcp), then record.

## Rollback — all preserved stores (nothing deleted, nothing modified)

- **`~/workspace/hydradb-run/sgk-local/store-fresh-1115`** — the
  Phase 16 store; went through the latest VM replacement + restart.
  Reads perfect, writes rejected. Previous live store.
- **`~/workspace/hydradb-run/sgk-local/store`** — the Phase 11 fresh
  store that later went through restarts; reads ok, writes rejected.
- **`~/workspace/hydradb-run/sgk-local/store-aged-20261115`** — the
  original Phase 11 aged store; reads ok, writes rejected.

To roll back to any of them: stop the node, start it with the script
that points at that store (`start-node-fresh1115.sh` for the 1115
store, the original `start-node.sh` for `store`), restart the app
server — accepting that report_outcome writes will fail there. The
fresh 1800 store can be abandoned simply by not pointing at it.
