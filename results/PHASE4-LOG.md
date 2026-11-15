# Phase 4 log — load test, live demo, write-ups

Started Sun 2026-11-15 ~00:41 IST. HydraDB `GET /healthz` on 18443 →
`{"status":"ok"}` before starting. Deadline Mon 2026-11-16 09:00 IST.

## Part 1 — load test (app/loadtest.py → results/loadtest.json)

50 concurrent agent threads × 3 rounds = 150 `find_tools` calls against
the live node, rotating over the 20 tasks with their stated roles.
CO_USED_WITH weights reset before and after (60 edges each time, same
`reset_outcome_weights` as run_phase2.py).

### Result — the node saturates; reported as measured

| metric | value |
|---|---|
| total calls | 150 |
| succeeded | 24 |
| errors | **126** |
| wall time | 246.42 s |
| throughput | 0.609 calls/s |
| latency mean / p50 / p95 / max | 70,682.1 / 69,587.9 / 104,299.4 / 131,818.8 ms |

All 126 errors are the same failure: `CypherError: HTTP 408` with body
`{"error":{"code":"query_timeout","message":"<stage> exceeded query
timeout after ~30000 ms; limit is 30000 ms"}}` — 45 distinct strings,
differing only by stage and elapsed ms. Stages seen:
`cypher_vertex_metadata`, `query_out_neighbors_scan`,
`cypher_vertex_write_back`. In plain terms: at 50-way concurrency the
single node on this shared 1.5-vCPU VM queues queries past its own 30 s
server-side timeout; a find_tools call makes ~7 sequential queries, so
most calls died part-way. Latency above includes the failed calls (each
burned one or more 30 s timeouts), which is why mean latency is ~64× the
single-agent benchmark latency (1,087.9 ms).

### Supplementary context run (results/loadtest-5agent.json)

Same protocol at 5 concurrent agents × 3 rounds = 15 calls: **0 errors**,
wall 47.56 s, throughput 0.315 calls/s, latency mean 15,288.6 ms /
max 19,962.0 ms. So the cliff is not at 50 — contention already inflates
per-call latency ~14× at concurrency 5 on this box. The routing code is
not the bottleneck (single-agent: ~1.1 s/call, 20/20 chains); the shared
VM + single node is. No numbers were re-run or filtered to look better;
both runs are kept in results/.

## Part 2 — live demo (app/server.py + app/demo.html)

Stdlib-only `ThreadingHTTPServer` on port 8077. Routes: `/` (demo.html),
`GET /api/tasks`, `POST /api/find_tools` (live `meta_tools.find_tools`,
role overridable), `GET /api/benchmark`, `GET /api/learning` (v1 + v2),
`GET /api/loadtest`.

Start command (HydraDB must be live on :18443 first):

```bash
bash ~/workspace/hydradb-run/start-node.sh   # if not running
python3 ~/workspace/waypoint/app/server.py   # http://localhost:8077
```

### Verification (server started, curled, then killed)

- `GET /` → **200**, body contains `WAYPOINT` (3 matches).
- `GET /api/tasks` → 200, 20 tasks + roles.
- `POST /api/find_tools {"task_id":"t03","role":"finance_agent"}` → chain
  `["lookup_customer","list_invoices","get_invoice","invoice_pdf",
  "find_contact","send_email"]` — the exact 6-tool chain; tokens_loaded
  494, round_trips 8, method `resolver`, entity Acme Corp → CustomerRef.
- `POST /api/find_tools {"task_id":"t04","role":"support_agent"}` →
  `refused: true, blocked_tool: "void_invoice", missing_scope:
  "payments:admin"` — the permission checkpoint fires live.
- `GET /api/benchmark`, `/api/learning`, `/api/loadtest` → all 200.
- Server killed after verification (port 8077 connection refused,
  curl exit 7). One operational note: the kill was done with a `pkill -f`
  pattern that also matched the invoking shell (SIGTERM to the exec
  session); the server process died with it, which the follow-up curl
  confirmed. Prefer `pkill -f 'waypoint/app/server.py'` from a separate
  shell or kill by PID.

Demo page design: single-file, near-black `#0c0a09`, 1px borders,
JetBrains Mono labels/numbers, Space Grotesk headings (Google Fonts with
system fallbacks), signal-orange `#ff4d00` only for numbers, the RUN
button, and the v2 curve line. Race table and curve are rendered from the
API JSONs, not hardcoded; the load-test panel states the 126-error result
and the saturation explanation on the page itself.

## Part 3 — write-ups

- `~/workspace/waypoint/README.md` — one-liner, problem, how it works
  (3 meta-tools, schema counts, MSpaths + validation + resolver,
  permission checkpoints, learning), the real benchmark table, the
  v1→v2 learning story, run instructions, honest limitations (TF-IDF =
  lexical baseline, token counts = definition-size estimates, shared-VM
  latency + load-test saturation, synthetic-but-typed catalog).
- `~/workspace/waypoint/PITCH.md` — buyer, pain in numbers, product,
  3-arm table, governance differentiator, learning curve, pricing story
  (per million tool resolutions / governance seat tier), the ask.

Every figure in both files was pulled from results/benchmark.json,
results/phase2.json, results/learning{,2}.json, results/loadtest.json —
no invented numbers.

## Files produced in Phase 4

- `app/loadtest.py`, `results/loadtest.json`, `results/loadtest-5agent.json`
- `app/server.py`, `app/demo.html`
- `README.md`, `PITCH.md`, `results/PHASE4-LOG.md`
