# PHASE 16 LOG — Local store rebuilt fresh; writes work again (2026-11-15)

## Why

Phase 15 restored the local stack after a VM replacement by restarting
the node on the existing store — and `report_outcome` writes failed
there with the known Phase 11 signature (`PutMode::Update not yet
implemented by LocalFileSystem`, HTTP 500). This engine build rejects
graph writes on any store that has been through stop/start cycles,
while a fresh store accepts them (Phase 15 judge-path check: 12/12 on a
fresh store, writes included). Tonight's demo video needs the local
write-back working, so the local store was rebuilt fresh — the
rehearsed Phase 11 remedy. No code was changed anywhere.

## How the node was pointed at the new store (the whole recipe)

`start-node.sh` hardcodes `LOCAL_PATH="$ROOT/store"` and its `fresh`
argument wipes the whole root — neither was used. Instead, a copied
script, **`~/workspace/hydradb-run/start-node-fresh1115.sh`**, is
`start-node.sh` with exactly these changes: `LOCAL_PATH` points at the
new store dir **`~/workspace/hydradb-run/sgk-local/store-fresh-1115`**,
and the pid/log/cache files are `node-fresh-1115.pid` /
`node-fresh-1115.log` / `cache-fresh-1115` so nothing of the old setup
is clobbered. Everything else is identical: same repo binary, same
ports (Bolt 17687 / HTTP 18443 / Admin 19091), same shared token file
(`~/workspace/hydradb-run/token.txt`), same env. The wipe mode was
deliberately not carried over — the script cannot delete anything.
Recovery next time = run that script, then `python3 app/seed.py`, then
`python3 app/ingest.py examples/real-mcp`, then start the app server.

## What was done

1. Stopped the old node (pid 4996, via its pid file) and the app
   server (`fuser -k 8077/tcp`). Ports confirmed free.
2. Started the node on the fresh store via the copied script —
   node pid **5403**, health `ok`.
3. `python3 app/seed.py` → **SEED VERIFY: PASS** (Tool=329; all node
   and edge counts exact).
4. `python3 app/ingest.py examples/real-mcp` → filesystem 14 new +
   memory 9 new; **tools 329 → 352 (23 ingested)**.
5. Restarted the app server against it (`nohup python3 app/server.py`,
   pid **5456**, log `~/workspace/hydradb-run/sgk-local/app-fresh-1115.log`).

## Verification — all on the fresh store

| Check | Result |
|---|---|
| Direct DB counts | **352 tools total / 23 ingested** |
| API t03 (finance_agent) | exact 6-tool chain, **494 tokens**, refused=false |
| API t04 as support_agent | **refused=true**, blocked `void_invoice`, missing `payments:admin` |
| `python3 app/prove_mcp.py` | **ALL PASS** — initialize, tools/list, find_tools (494 tok), resolve_entity (Acme Corp → CustomerRef, id 302), t04 refusal, and **report_outcome: 5 edges written, weights 0 → 1 on all five** (the write that returned HTTP 500 on the old store) |
| `python3 app/run_phase2.py` | chains **20/20** (set + exact order), refusals **3/3**, avg 253.7 tok, 13 MSpaths / 7 resolver — identical to the Phase 3 gate; its weight-reset writes also succeeded |
| GET / and GET /console | **200 / 200** |
| GET /api/agent_feed | returns entries — newest are the proof calls, report_outcome first |

## ⚠️ Do not restart the node before the video

Both processes are left running (node 5403 on the fresh store, app
5456 on :8077). **From this moment the HydraDB node must NOT be
restarted again before tonight's demo video / submission** — a
stop/start cycle is exactly what makes this engine build reject
writes on a store. If a restart is forced anyway, re-run
`python3 app/prove_mcp.py` immediately and, if report_outcome 500s,
repeat this rebuild with a new store dir.

## Rollback

The previous store is intact, untouched, at
**`~/workspace/hydradb-run/sgk-local/store`** (the Phase 11 fresh store
that later went through restarts; reads perfect, writes rejected).
The Phase 11 aged store also remains at `store-aged-20261115`. To roll
back: stop the node, start it with the original
`~/workspace/hydradb-run/start-node.sh` (which points at
`sgk-local/store`), restart the app server — accepting that
report_outcome writes will fail there. Nothing was deleted; the fresh
store can be abandoned simply by not pointing at it.
