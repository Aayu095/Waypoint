# PHASE 14 — Hero as one continuous flow + vertical centering (2026-11-15)

Aashi's verdict on Phase 13: the dwell-then-flip still felt like two static
pages with a pause between them, and the flood headline rode too high.
Both fixed in `site/index.html` only, proven in motion, and redeployed.

## The new hero flow (replaces dwell-then-flip)

- **Stage A — FLOOD (hold 1,400 ms):** the full 329-chip flood, headline,
  task bar, counter at 27,000. The Phase 13 dwell machinery (5s visible-time
  clock, IntersectionObserver pause, visibility pause) is GONE — a plain
  `scheduleAuto()` timer remains. "Route it" click skips straight to the melt.
- **Stage B — THE MELT (~3.5 s, no cut, no pause):**
  - Flood recession is now staggered **by position**: each chip's delay is
    `(1 − distFromHeroCentre/maxDist) × 1.6s + ≤0.2s random`, duration 1.6s —
    edges recede first, the centre lingers last; the field visibly thins like
    a tide going out instead of switching off (was: random 0–0.35s delay, 0.8s).
  - Counter tweens 27,000 → 494 over the **same 3.5 s**, easing changed from
    ease-out cubic to **ease-in-out cubic** so it is mid-flight when the melt
    is. A `tickGen` guard stops a stale rAF from overwriting a replay.
  - Headline swap is now a true **crossfade**: both blocks get a 2.2s
    transition and swap at melt +0.4s. The outgoing block's `visibility` is
    forced on inline first — the `.hidden` class sets `visibility:hidden`,
    which would otherwise pop it out instantly instead of dissolving.
  - The 6 chain chips **light up in place**, one by one (melt +0.5s, 0.2s
    stagger), still sitting in the flood — then at +1.7s the existing FLIP
    glide (extracted as `glideChips()`, 1.4s glide, 0.06s stagger) flies them
    home. `#pathline` is now gated on a new `body.lining` class added at
    glide start, so the line grows with the glide, not at melt start.
  - **Settle preserved exactly** (extracted as `settleChips()`, now at
    melt +3.3s): renders the 6 chips in-flow in `#pathrow`, adds
    `body.snaproute`, and **removes the fixed copies from the DOM** — the
    Phase 13 root-cause fix is untouched in mechanism, only retimed.
    A `routeGen` guard still protects every melt timeout against replay.
  - `body.landed` is added at settle: sub-line, CTAs and `#pathcap` reveal
    only then (see alignment). Snap mode adds `landed` synchronously.
- **Stage C — RESOLVED:** the established end composition (Phase 13 chip
  sizes, micro-line, sub-line, CTAs, footer sign-off). "Route it again"
  resets and re-arms the 1.4s hold — the whole flow replays from Stage A.
- `prefers-reduced-motion` → instant resolved, as before. `?state=flood` /
  `?state=resolved` snap holds unchanged (re-verified below).

## Alignment fix

The column was centred as a whole, but in flood state the sub-line and CTAs
sat invisible-yet-space-occupying below the readout, dragging the visible
group (badge → counter) into the upper third. Now:
- `.subline` / `.ctas` are **collapsed pre-`landed`** (`max-height:0`,
  `margin-top:0`, `overflow:hidden`) and expand with a 0.7s
  max-height/margin/opacity transition when `landed` lands — the flood
  column is only badge, headline, task bar, path stage, counter, and flex
  centres exactly that.
- `.hl` is `justify-content:center` with `min-height:212px` (was flex-start /
  196px), `margin-top:34px`; hero vertical padding symmetrised (56/56).
- Result at 1600×1000: flood group spans ≈205–690px (centre ≈450 vs
  viewport 500 — optically centred; task bar sits in the middle band);
  resolved group spans ≈205–815 (centre ≈510). At 1440×900 the flood group
  centres at ≈415 vs 450. Headline no longer rides the upper third in
  either state.

## Proof — IN MOTION (puppeteer, local server, real animated flow)

Script: `~/workspace/tools/pptr/waypoint-fix14-proof.mjs` (+ `-replay.mjs`).
Every screenshot read by hand.

- `waypoint-fix14-flood06.png` (t≈0.6s) — pure flood, `routed=false`,
  counter 27,000; headline group in the middle band. (The "…to send one
  email." line fades in at start +0.3s over 0.7s, so at 0.6s it is still
  arriving; it is fully in by ≈1.6s, before the melt begins ≈1.95s.)
- `waypoint-fix14-melt32.png` (t≈3.2s) — **mid-melt on every axis**: flood
  visibly thinned unevenly (DOM count at capture: 172 chips still solid,
  150 mid-fade, 1 ghost), counter caught at **23,339** (DOM) / 22,289
  (frame) — neither endpoint; **4 of 6 chain chips lit in place** inside
  the flood; both headlines visible at once, dissolving; button "Routing…".
- `waypoint-fix14-resolved7.png` (t≈7s) — resolved composition identical
  to the established end state. DOM assertions: `fixedChipsInBody=0`,
  `pathrowChips=6`, `tok=494`, `snaproute=true`, `landed=true`,
  button "Route it again ↺". ✓
- `waypoint-fix14-scroll500.png` — Phase 13 regression: THE RACE heading +
  "A vector store guesses similar tools…" fully uncovered; hero bottom
  scrolling away in normal flow. ✓
- `waypoint-fix14-flood1440.png` (1440×900) — flood composition centred at
  the smaller viewport. ✓
- Replay test: after resolving, "Route it again" → flood fully restored
  (unrouted, 27,000, path row empty), melt replays, resolves identically
  (0 fixed chips, 6 path chips, 494). `?state=resolved` → instant settled
  end state; `?state=flood` → still unrouted after 2.5s. ✓
- Note: the capture browser logs one `ERR_TUNNEL_CONNECTION_FAILED` for the
  Google Fonts stylesheet (this VM's egress blocks the headless shell);
  real visitors load the webfont normally — Aashi's own live screenshots
  show it. Not a site defect.

## Environment notes

- The app server (8077) and the HydraDB node were both down when this phase
  started (VM replacement). The app server was restarted for the proof
  (`python3 app/server.py`, site serves 200). **The HydraDB node was NOT
  restarted** (per freeze rule) — it does not answer on 18443; flagged to
  the parent agent, the website proof does not depend on it.
- `/tmp/waypoint` had been wiped with the VM, so the deploy bundle was
  rebuilt from scratch: new `index.html` + the `/console` page recreated
  with the same honest content (live captures + install path) and the same
  three console captures from `results/shots/` (`waypoint-spacing-t03.png`,
  `waypoint-product-graph.png`, `waypoint-spacing-evidence.png`), then
  re-linked to the existing `waypoint` Vercel project.

## Redeploy

`vercel deploy --prod --yes --scope aayushi-team` from `/tmp/waypoint` →
https://waypoint-nine-iota.vercel.app — curl-verified `/` 200, `/console`
200, and the served HTML contains the new melt code (`glideChips`,
`DWELL_MS = 1400`).

No other repo files touched. App server left running.
