# Phase 6 — Product-grade console UI (demo.html rewrite)

**Why:** the Phase 4 demo page was a stacked report (panels + paragraphs).
The user rejected it outright. Phase 6 rebuilds it as a dense, interactive
console in the Linear/Vercel dark-engineering idiom, with the live graph
as the hero. Everything displayed still comes from the same live APIs —
no scripted or fake states anywhere.

## Backend addition (server.py — additive only)

- New route `GET /api/graph`, built per-request from the LIVE HydraDB via
  `client.run` (4 Cypher pulls: tools, INPUT_TO, OUTPUT, REQUIRES_SCOPE):
  the 41 core tools `{key, server, tokens, scopes}`, the 42 DataTypes they
  consume/produce, 87 typed edges, and counts computed from the DB
  (total_tools 329, core 41, distractors 288). Nothing is read from
  tools.json. All pre-existing routes untouched and re-verified (200s +
  POST /api/find_tools refusal for t04/support_agent).

## Console layout (single file, vanilla JS + inline SVG, no build step)

- **Top bar (47px):** WAYPOINT® wordmark + tagline; live chips filled from
  the APIs — catalog 329 · preload 27,000 · graph ~254 · chain acc 20/20 ·
  distractors 288 · load 33.2 calls/s.
- **Left rail:** 20 task rows (id, truncated text, chain-length badge from
  benchmark per-task data), 8 role pills (selecting a task applies its
  stated role; overriding the pill is how refusals are demoed), orange RUN.
- **Center — the graph (hero):** SVG network from /api/graph. Tools =
  labeled pills, DataTypes = small squares with labels.
- **Right rail — inspector:** run telemetry (status, method, db_queries,
  snapshot cache hit/miss, round_trips, client-measured latency, route),
  resolved entity (name → ref type), per-tool scope checklist with ✓/✕
  against the selected role's scopes, a node inspector (click any tool
  node: server / tokens / scopes), and an execution ticker logging the
  real API exchanges only.
- **Bottom bento (198px, zero prose):** THE RACE — 3 log-scale token bars
  from benchmark.json; LEARNING — v1/v2 pass-accuracy SVG chart from
  /api/learning; UNDER LOAD — before/after big-number pairs (126 err ·
  0.61/s → 0 err · 33.2/s) from loadtest.json + loadtest2.json (50-agent
  run); GTM — buyer / pricing / governance / moat as pills.

## Graph layout approach

Directed BFS layering over the bipartite type→tool→type graph:

1. Roots = DataTypes produced by no core tool (CompanyName, RepoName,
   TeamName, TicketRef). Layer = BFS distance; layers alternate
   type/tool and read as a top→down flow.
2. Disconnected components are entered afterwards via a task start type
   inside them — this is what places the DocText cycle component
   (DocText → search_drive → FileRef → ocr_scan → DocText), which has no
   source type. (An undirected/first-pass BFS and rooting on *all* task
   start types both collapsed the layout into 5 mega-bands; directed BFS
   with component entry gives 9 legible layers, max 17 nodes.)
3. Four alternating barycenter sweeps cut edge crossings; each layer is
   packed left→right and wraps to a sub-row when it exceeds the width.
4. Edges are cubic beziers at 10% white; state (hover / lit / blocked)
   raises them. Hovering a tool highlights its neighbourhood; the
   resolved path is drawn over the texture in orange.

## Run animation

On RUN the page POSTs to /api/find_tools (unchanged live path), then
walks the returned chain: for each tool, a pulse dot travels along each
input edge from an already-available type (~190ms), the tool lights
orange with a ring, then its output edges pulse and produced types
light. Joins (e.g. t03's EmailAddr + InvoicePdf branches into
send_email) converge visibly. On refusal the prefix lights, the blocked
tool gets a red ✕ checkpoint badge + shake, later chain chips dim, the
token meter shows ✕ / 0 loaded, and the scope checklist marks the
missing scope. `&instant=1` (with the existing ?task=&role=&run=1 deep
links) skips only the pulse pacing and lands on the settled state of
the same live result — added for screenshots/video; deep links without
it behave exactly as before.

## Verification (headless Chrome, this machine)

- `results/shots/waypoint-t03-chain.png` (1440×1000, deep link +
  instant): full 6-tool path lit across the graph incl. the find_contact
  branch, chain strip lit, 98.2% saving / 494 tok, telemetry RESOLVER ·
  2 dbq · cache HIT, all scopes ✓, entity Acme Corp → CustomerRef.
- `results/shots/waypoint-t04-refused.png` (1440×1000): path prefix lit,
  void_invoice marked with red ✕ badge, chain strip shows the blocked
  chip, meter ✕ refused · 0 loaded, checklist ✕ payments:admin, ticker
  shows the real POST + REFUSED response line.
- `results/shots/waypoint-full.png` (1440×2400): initial console, all
  20 tasks, graph, bento — everything rendered from live data.
- One layout fix round was needed and used: (1) directed BFS +
  component entry replaced the collapsed undirected layering;
  (2) `instant=1` added after the first run-state shots caught the
  animation mid-flight under virtual-time screenshots.

## Not touched

benchmark.json / learning.json / learning2.json / loadtest*.json,
meta_tools.py logic, client.py, seed/catalog/tasks. server.py gained
exactly one route. Demo server left running on :8077.
