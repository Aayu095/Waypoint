# PHASE 8 LOG — the product screen (frontend rebuild)

Date: Sun 2026-11-15 (IST). Scope: `app/demo.html` only. No backend file,
results JSON, or meta_tools logic was touched; server.py unchanged.

## Why

Phase 6's console led with the graph — our plumbing. A buyer/judge saw a
database, not a product doing a job. Phase 8 reframes the screen around the
project's headline — *a tool-routing graph for agents, built on HydraDB,
with a Track 1-style learning curve* — and demotes permissions to a
supporting beat (one tag on one card + one line), where they belong.

## The idea

The hero visual is **the agent's context window**:

- WITHOUT Waypoint the window floods with the whole catalog before the
  agent can start (329 tools · 27,000 tokens, every task, every time).
- WITH Waypoint the same window receives exactly the routed chain
  (t03: 6 tool cards · 494 tokens · **98.2%** saved — the biggest number
  on the page).

The contrast needs no reading and lands in ~3 seconds. The graph didn't
die — it moved to its proper home, "Under the hood", for engineering
judges.

## What was built (single file, vanilla JS + inline SVG, no build)

Shell: slim top bar (WAYPOINT® + tagline + live chips, all from the APIs:
CATALOG 352 = 329 benchmark + 23 ingested · PRELOAD 27,000 · GRAPH AVG
~254 · CHAIN ACC 20/20 · LOAD 33.2 calls/s), a narrow left nav rail
(RUN / GRAPH / EVIDENCE), and one persistent composer (20 task rows with
full readable text + chain-length badges, the 8 benchmark role pills,
RUN). Selecting a task resets the stage; selecting a task also applies
its stated role, overriding the role is how a checkpoint is hit.

- **RUN (default)** — two agent-context windows side by side.
  Left (PRELOAD ALL) is static and honest: the 41 core tool chips from
  /api/graph, a 14-name sample of real distractor tools named in
  benchmark.json's vector arm, and a "+274 more tools" tile (288
  distractors − 14 shown); full red-brown token bar; the status line
  "tokens spent before the task even starts · every task, every time".
  Right (ROUTED) starts empty ("Waiting for a task"); on RUN it calls
  the unchanged live /api/find_tools and animates the chain in as
  proper cards (step №, name, server, tokens) ~200 ms apart while the
  token counter counts to the real tokens_loaded and the bar fills
  proportionally vs 27,000. Result strip: an authored readiness line
  per task ("Ready: March invoice addressed to Acme Corp's finance
  contact" — readiness only; nothing claims the email was sent) +
  "chain resolved in N tools · X tokens · Y graph queries".
  Refusal: cards stop at the blocked tool, which lands with an orange
  ✕ CHECKPOINT tag, the counter stays 0, and there is exactly one
  line — "Stopped: void_invoice needs payments:admin, which
  support_agent doesn't hold." No panel, no headline.
  Under the stage, three chips-only strips, all numbers fetched:
  LEARNS FROM OUTCOMES (mini v2 curve + 0.85 → 0.95), HOLDS UP UNDER
  LOAD (50 agents · errors 126 → 0 · 33.2 calls/s · p95 2,259 ms),
  BEATS VECTOR ON CHAINS (full chain 8/20 vs 20/20 · 823 vs 254 tok).
- **GRAPH** — the Phase 6 experience reused wholesale (layout engine,
  pulse-along-edge path animation, blocked-node ✕ + shake, chain
  strip, token meter, inspector with telemetry / entity / scope
  checklist / node inspector / real-API ticker). It renders lazily at
  real width on first activation and re-applies the last run.
- **EVIDENCE** — the numbers room: THE RACE (3 arms, log-scale bars,
  with the honesty note that arm B is a TF-IDF lexical baseline, not
  neural embeddings), LEARNING full-size (v1 grey 0.40 → 0.35 vs v2
  orange 0.85 → 0.95, v1's failure labelled, not hidden), UNDER LOAD
  (126 err · 0.61/s → 0 err · 33.2/s + per-level pills for 10/25/50
  agents), INGESTION (baked statically from results/ingest-real.json:
  23 real tools from the official filesystem + memory MCP servers,
  graph 329 → 352, idempotent re-ingest, the r1/r2/r3 chains and the
  fs_reader checkpoint on real tools), and the MCP-server panel
  (find_tools / resolve_entity / report_outcome over stdio JSON-RPC,
  proof transcript cited).

Deep links: `?task=t03&role=finance_agent&run=1` opens RUN and runs;
`&instant=1` settles animations immediately (screenshots);
`?view=graph|evidence` added so the other views are linkable too.

## Verification (headless Chrome, 1440×1000, screenshots read by eye)

- `shots/waypoint-product-run.png` — initial RUN: flood vs empty
  window contrast is instant; all five top chips live; strips filled.
- `shots/waypoint-product-t03.png` — 6 cards in order, 494 tok,
  **98.2%** dominant, readiness line + "6 tools · 494 tokens · 7 graph
  queries". (Warm-cache runs report fewer db queries — real behaviour,
  the number is whatever the live call returns.)
- `shots/waypoint-product-refused.png` — t04 as support_agent: cards
  halt at void_invoice with the ✕ CHECKPOINT tag, 0 tok loaded, the
  single Stopped line. Permissions read as a beat, not the headline.
- `shots/waypoint-product-graph.png` — graph view intact: t03 path
  lit end-to-end incl. the find_contact join, inspector RESOLVED,
  scope checklist all ✓, ticker shows the real exchange.
- Bonus: `shots/waypoint-product-evidence.png` (1440×1560) — all five
  evidence panels render from the artifacts.
- No layout fix round was needed: the one allowed fix condition
  (stage contrast not instantly readable) did not trigger.

## Environment notes

This VM appears to have been replaced again: HydraDB and the demo
server were down and `/usr/bin/google-chrome-stable` is gone. HydraDB
was restarted via `~/workspace/hydradb-run/start-node.sh` against the
existing store (never wiped — /api/graph confirms 329 + 23 ingested
tools intact), the demo server was restarted on :8077, and screenshots
were taken with the puppeteer chrome-headless-shell at
`~/.cache/puppeteer/chrome-headless-shell/linux-156.0.8078.47/…`
(`/opt/meta-chromium/chrome` refuses to start: "Hatch WebGL domain
policy is required"). Both servers are left running.

## Honest gaps

- The routed window is tall; a 2–6 card chain leaves deliberate empty
  space under the cards. That emptiness is the message (a nearly
  empty context vs a flooded one), but a denser chain (none exists in
  the benchmark) would fill it.
- The preload window shows 55 named chips + a "+274 more" tile rather
  than all 329 names; the count is exact and the sample distractors
  are real names from the benchmark artifact.
- Evidence view's learning chart has a slight label collision at the
  left axis (0.5 gridline vs v1's 0.40 point label). Cosmetic only.
- Readiness lines are authored per task (20 lines in demo.html); an
  unknown task id falls back to "Ready: <goal type> resolved".
