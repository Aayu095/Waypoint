# PHASE 15 — Hero lag fix, footer redesign, MCP judge-path check (2026-11-15)

Three jobs before tonight's freeze: (0) recover the local stack after a VM
replacement, (1) remove the melt's jank without changing its look/timings,
(2) rebuild the footer, (3) prove the MCP server end-to-end exactly as a
judge would run it — on a fresh store. Plus (4) redeploy.

## 0 · Stack recovery

The VM replacement had killed the node and wiped system libs (the parent's
backgrounded `apt-get update` + `libgraphblas-dev` install completed during
this phase — `ldconfig` shows libgraphblas.so.7 again). Started the node
with `~/workspace/hydradb-run/start-node.sh` on the EXISTING store (no
wipe): health ok, **352 tools / 23 ingested** verified by direct query,
app on :8077 answering, t03 via API exact at 494.

## 1 · Hero lag fix (site/index.html, hero only)

Diagnosis — the melt transitions ~323 flood chips at once; the expensive
parts were: an **animated `filter: blur(1px)`** on every receding chip,
a standing **`will-change: transform, opacity` on all 329 chips** (329
promoted layers), a stagger that peaked at ~290 concurrent transitions,
and a counter that wrote to the DOM on **every** rAF frame.

Fixes (flow look and Phase 14 timings untouched — flood 1.4s, melt ~3.5s,
glide at +1.7s, settle at +3.3s):
- `.chip`: transition list is now transform+opacity (+ colour props);
  `filter` removed from the transition and from `.chip.gone` (at 4.5%
  opacity the blur was invisible anyway). `will-change` removed.
  Added `contain: layout paint` per chip.
- Stagger widened (delays 0–2.05s, per-chip fade 1.6s → 1.3s): same ~3.4s
  melt envelope, peak concurrent transitions ~290 → ~205.
- `tickCounter`: DOM write only when the displayed string changes.
- `glideChips`: `will-change: transform` set on the 6 chain chips only,
  for the glide only (settle removes the elements; reset clears inline
  styles on replay).

Frame times (puppeteer rAF sampler over the melt window; rough headless
measurement — SwiftShader on a shared 1.5-CPU VM, so absolute numbers are
pessimistic, the before/after delta is the signal):
- BEFORE: avg **60.2 ms**, p95 **100 ms**, 24 frames >50 ms, 60 frames in window
- AFTER:  avg **34–35 ms** (two runs: 35.3 / 34.1), p95 **66.7 ms**,
  11 frames >50 ms, ~104 frames in window — ~43% lower average frame
  time, ~75% more frames rendered through the same melt.

Proof (`waypoint-fix15-melt.png`, read by hand): mid-melt character
unchanged — counter caught at 22,958, flood thinned unevenly, 3 of 6
chain chips lit in place, headlines mid-crossfade. Resolved end state
DOM assertions: fixedChipsInBody=0, pathrowChips=6, tok=494,
button "Route it again ↺". Script: `~/workspace/tools/pptr/waypoint-fix15-perf.mjs`
+ `waypoint-fix15-proof.mjs`.

## 2 · Footer redesign (site/index.html footer only)

Rebuilt as a proper closing on the sections' own column (max-width
1180px, 32px side padding — same geometry as `main`): padding 48px top /
40px bottom; sign-off "Waypoint — agents pull only what the task needs."
centred; a 1px divider; then one balanced row — left **WAYPOINT®**
wordmark (orange ®), centre "Built on HydraDB · HydraDB Hackathon ·
Track 2 · Solo build", right the pricing chip unchanged. Under 900px the
row stacks centred. Proof: `waypoint-fix15-footer.png` (read by hand) —
wordmark, centre credits and chip all sit on the same column edges as
the Install card above; nothing hugs a viewport edge.

## 3 · MCP judge-path check — 12/12 PASS on a fresh store

Method: stopped the running stack, then `WAYPOINT_STORE=<scratch>
./run.sh` (documented path; HYDRA_SRC pointed at the local HydraDB
checkout, run.sh's own knob) — it created the store, seeded (SEED VERIFY
PASS, 329), ingested (352 total) and started the app, alone. Then the
new `app/check_mcp.py` drove `python3 app/mcp_server.py` over stdio from
the repo root, exactly per the README config:

| # | Check | Result |
|---|-------|--------|
| 1 | initialize handshake (waypoint, protocol 2024-11-05) | PASS |
| 2 | tools/list = exactly [find_tools, resolve_entity, report_outcome] | PASS |
| 3 | every tool has inputSchema (object, properties, required) | PASS |
| 4 | find_tools t03 → exact 6-tool chain, 494 tok | PASS |
| 5 | find_tools t04 as support_agent → REFUSED void_invoice / payments:admin | PASS |
| 6 | find_tools filesystem copy (FilePath→WriteFileOutput, fs_agent) → [read_file, write_file], 230 tok | PASS |
| 7 | resolve_entity 'Acme Corp' → CustomerRef (id 302) | PASS |
| 8 | report_outcome success → 5 edges, weights 0→1 | PASS |
| 9 | report_outcome failure → weights 1→0 (rules: −1, floor −5) | PASS |
| 10 | DB cross-check of an edge weight matches the tool result | PASS |
| 11 | protocol purity: all 8 stdout lines valid JSON-RPC 2.0 | PASS |
| 12 | agent-calls.jsonl gained exactly 6 entries (one per tools/call) | PASS |

Scratch stack then torn down; the ORIGINAL stack was restored
(start-node.sh + app server) and re-verified: health ok, 352 tools,
t03 via API exact chain at 494, / and /console 200.

### ⚠️ Finding on the restored local store (not an MCP-server bug)

Re-running `prove_mcp.py` against the restored local store passed every
read (initialize, tools/list, find_tools, resolve_entity, refusal) but
**report_outcome returned HTTP 500**. Node log shows the known Phase 11
signature verbatim: `put_opts with mode PutMode::Update not yet
implemented by LocalFileSystem`. Micro-diagnostics: on this reopened
store even a MERGE creating a brand-new CO_USED_WITH edge 500s, while
all reads are perfect — i.e. after the store has been through stop/start
cycles, the engine build rejects graph writes on it; a fresh store
accepts them (proven today, checks 8–10). No stray data was written by
the diagnostics (the test MERGE failed; read-back empty).

Impact: **judges are unaffected** — their first run is a fresh store
(12/12 above, writes included). Locally, the console/video read paths
are unaffected (t03 API verified post-restore). Only the write-back
(report_outcome) fails on this particular reopened local store. The
rehearsed remedy, if local writes are wanted tonight: rebuild the local
store fresh via run.sh with a new WAYPOINT_STORE (~1 minute, counts
identical) and then do not restart the node again before the video.
Not applied here — the call belongs to the parent/Aashi, and the freeze
rule says the node is not restarted casually.

## 4 · Redeploy

Bundle in /tmp/waypoint (new index.html + the preserved /console page
and its 3 images, project link intact) →
`vercel deploy --prod --yes --scope aayushi-team`. Curl-verified:
https://waypoint-nine-iota.vercel.app/ = 200, /console = 200, and the
served HTML contains the new footer markup (`.wm` wordmark + centre
credits line) and the Phase 15 perf CSS (`contain:layout paint`).

## End state

Original stack left running: graph-node pid 4996 on the real store
(health ok, 352 tools) + app server pid 5027 on :8077 (/ and /console
200). Files changed: site/index.html (hero perf + footer), new
app/check_mcp.py (the judge-path check, kept in the repo), this log,
results/shots/waypoint-fix15-{melt,resolved,footer}.png. Engine logic
untouched; no other repo files changed.
