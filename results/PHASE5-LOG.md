# Phase 5 log — snapshot cache: the load test found it, the re-test proves it

Started Sun 2026-11-15 ~00:48 IST. Deadline Mon 2026-11-16 09:00 IST.
HydraDB live on :18443 throughout. Phase 3's `benchmark.json` and the
learning JSONs were NOT touched — the benchmark stands as the uncached
measurement; this phase adds a new measurement, it does not rewrite one.

## Diagnosis (from Phase 4)

Every `find_tools` call re-pulled the full catalog from HydraDB — tools,
inputs, outputs, requires, scopes — plus a native MSpaths call and an
entity lookup: ~7 sequential HTTP queries per call. Single-agent that is
fine (mean ~1.1 s, 20/20 chains). At 50 concurrent agents the single node
on this shared 1.5-vCPU VM queued those queries past its own 30 s
server-side timeout: **126/150 calls errored, all HTTP 408
`query_timeout`**; even 5 agents already showed 15.3 s mean latency. The
routing logic was never the bottleneck — the repeated full-graph pulls
were.

## The fix — snapshot cache in app/meta_tools.py

- The five bulk metadata pulls are loaded from HydraDB **once per
  process** into a snapshot and served from memory after that.
- **Invalidation:** (a) TTL 60 s; (b) immediately on any `report_outcome`
  write in the same process (the only write path in meta_tools).
- **What still goes live on every call:** the native `algo.MSpaths`
  traversal (the traversal we showcase) and the `resolve_entity` point
  lookup. If MSpaths validation fails, the fallback resolver now runs
  over the cached snapshot instead of freshly pulled edges. A warm
  `find_tools` therefore issues **2 HTTP queries instead of ~7**.
- **Thread-safety:** snapshot load/refresh is guarded by a lock with a
  re-check, so a concurrent burst shares one load instead of stampeding
  the node with identical pulls.
- **Honest metrics:** `find_tools` still returns `round_trips` counted
  exactly as the uncached algorithm counted them (logical round trips —
  Phase 2/3 comparability preserved), and now also returns `db_queries`
  (actual HTTP queries this call issued) and `cache_hit` (True when the
  snapshot was warm and cost 0 queries). Unit check in one process:
  cold call db=7 / hit=False → warm call db=2 / hit=True, identical
  chain and identical round_trips=8 → after `report_outcome`, db=7 /
  hit=False again (write invalidation works).

## Re-test — app/loadtest2.py → results/loadtest2.json

Same protocol as Phase 4 (rotating 20 tasks, stated roles, weights reset
around each level), three levels in one process, run in 10 → 25 → 50
order, no level re-run or dropped:

| level | calls | errors | wall | throughput | latency mean / p50 / p95 / max (ms) | cache hits | DB queries / call |
|---|---|---|---|---|---|---|---|
| 10 agents × 3 | 30 | **0** | 5.90 s | 5.09 /s | 1,773 / 695 / 4,347 / 4,554 | 29/30 (96.7%) | 2.17 |
| 25 agents × 3 | 75 | **0** | 1.83 s | 40.97 /s | 503 / 477 / 1,015 / 1,209 | 75/75 (100%) | 2.00 |
| 50 agents × 3 | 150 | **0** | 4.52 s | 33.20 /s | 1,235 / 1,171 / 2,259 / 2,880 | 150/150 (100%) | 2.00 |

### Before / after at 50 agents (the Phase 4 failure, re-measured)

| metric | Phase 4 — uncached | Phase 5 — snapshot cache |
|---|---|---|
| calls | 150 | 150 |
| errors | **126** (all HTTP 408 query_timeout) | **0** |
| wall time | 246.42 s | 4.52 s |
| throughput | 0.609 calls/s | 33.20 calls/s |
| latency mean | 70,682 ms | 1,235 ms |
| latency p95 | 104,299 ms | 2,259 ms |
| latency max | 131,819 ms | 2,880 ms |
| DB queries per call | ~7 | 2.00 |
| logical round trips per call | 7.35 | 7.35 (unchanged, by construction) |

### Reading the table honestly

- The 10-agent level carries the run's worst p95 (4,347 ms) because it
  ran first in the process: it absorbed the one cold snapshot load
  (29/30 hits — the first call paid the 5-query load) and cold-start
  contention. The 25- and 50-agent levels ran fully warm, which is also
  why the 25-agent wall time (1.83 s) beats the 10-agent one (5.90 s).
- Because all three levels share one process (like a long-lived demo
  server), **the 50-agent run started with a warm cache. A cold-cache
  50-agent burst is untested** — the first such call would pay one
  5-query load under the lock while the rest wait, by design.
- Nothing above 50 concurrent agents was tested. On this box, 50 is now
  clean; the honest capacity claim is "50 concurrent agents, 0 errors,
  on a shared 1.5-vCPU VM" — not more.

## Regression sanity — run_phase2.py re-run

Fresh process, snapshot loads fresh: **chain accuracy 20/20 (set and
exact order), refusals 3/3**, avg tokens loaded 253.7, avg logical
round_trips 7.35, methods 13 mspaths / 7 resolver — identical to the
Phase 3 numbers. The cache changed no result, only the query count.
(`results/phase2.json` refreshed by the re-run.)

## Demo verification (server started, curled, killed)

- `POST /api/find_tools t03 / finance_agent` (cold, first call in the
  server process) → exact 6-tool chain `lookup_customer, list_invoices,
  get_invoice, invoice_pdf, find_contact, send_email`; tokens 494,
  round_trips 8, **db_queries 7, cache_hit false**.
- Same call again → same chain, **db_queries 2, cache_hit true**.
- `POST /api/find_tools t04 / support_agent` → `refused: true,
  blocked_tool: void_invoice, missing_scope: payments:admin` (served
  warm: db_queries 2).
- `GET /api/loadtest2` → 200, all three levels present; demo page's
  UNDER LOAD panel now renders the Phase 4 "before" block and the
  Phase 5 per-level "after" table from the two JSONs.
- Server killed by PID and confirmed stopped (port 8077 free, curl exit
  7). Operational note: the `nohup … &` wrapper reported a PID two off
  from the real python process (20924 vs 20926) and `pgrep -f` kept
  matching the probing shell's own command line — trust `ss -ltnp` /
  `ps` for the listener's real PID.

## Files produced / changed in Phase 5

- `app/meta_tools.py` — snapshot cache, invalidation, db_queries /
  cache_hit fields (round_trips semantics unchanged)
- `app/loadtest2.py`, `results/loadtest2.json` — the 10/25/50 re-test
- `app/server.py` — new `GET /api/loadtest2` route
- `app/demo.html` — UNDER LOAD panel: before (Phase 4) + after (Phase 5)
- `README.md` — Phase 5 paragraph, updated latency limitation
- `results/phase2.json` — refreshed by the sanity re-run (same numbers)
- `results/PHASE5-LOG.md` — this file
