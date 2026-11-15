# PHASE 17 — Evidence sections come alive on scroll (2026-11-15)

Aashi's direction: the hero is all motion (flood → melt), but everything
below "See the evidence ↓" was static. The five evidence sections now
animate as a judge scrolls to them. Every animation ends on EXACTLY the
values the page already printed statically — no new numbers, no new
claims. Only `site/index.html` changed (plus this log + screenshots).
Hero, footer, console, app code and the DB untouched.

## Mechanism

One IntersectionObserver (threshold 0.35, fire ONCE per section, then
unobserve) adds `.inview` to `#race`, `#learns`, `#load` (the brief's
"#holds" — the section's actual id), `#ingest` (04), `#install` (05).
All pre-animation states live ONLY under `html.ev`, a class the new
script adds when — and only when — animation will actually run: JS on,
no `prefers-reduced-motion`, no `?state=` shot mode, IntersectionObserver
present. Without `ev`, no pre-state CSS applies and the page renders
final-state exactly as before (JS-off included). Counters are parsed
FROM the live DOM text (target, "~" prefix, comma style) and each
counter's final frame writes its original string back, so a settled
page is textually identical to the pre-change page. Animated
properties: transform, opacity, stroke-dashoffset only — no animated
filter/blur/shadow (Phase 15), no layout shift (race bars scaleX inside
their existing tracks; final sizes are the layout sizes).

## What animates where

- **01 · #race THE RACE:** the three bars grow 0 → final width
  (scaleX, 1.2s, staggered 0/.15/.30s — preload, vector, graph last),
  and each row's headline number ticks up in step (27,000 / 823 / ~254,
  same stagger). Only the first `<b>` of each stat is a counter — the
  "8/20" inside the vector row's sentence is never touched.
- **02 · #learns IT LEARNS:** the v1 (grey, failed) line + dots + labels
  fade in plainly first (0.7s) and stay flat; then the v2 curve draws
  itself left→right (pathLength-normalised dashoffset, 1.2s from +0.3s)
  with its 4 dots and 3 labels fading in in sequence as the line
  reaches them (0.85 → 0.90 → 0.95). Side cards rise subtly, staggered.
- **03 · #load IT HOLDS UP:** cards land in story order (before →
  arrow → after, fade/rise). BEFORE counts up to its printed breakage
  (126, 0.61); AFTER counts errors DOWN 126 → 0 while throughput climbs
  0 → 33.2 (both from +0.7s, 1.1s). The section prints no latency
  figures, so none were animated (the brief's condition).
- **04 · #ingest + 05 · #install:** cards/codecard/chip rows rise
  10px + fade in, staggered ~0.12–0.26s. Understated, no gimmicks.

Total per section ≈ 1.5–1.8s, ease-out throughout.

## Proof (puppeteer, local app server, 1600×1000)

Baseline captured BEFORE the edit (`waypoint-fix17-base-{race,learns,
load,ingest,install}.png` + a DOM "truth" dump: race stats
["27,000","823","8/20","~254"], fill widths [640, 421.109, 346.875]px,
load values ["126","0.61","0","33.2"], all 14 SVG labels).

Scripts: `~/workspace/tools/pptr/waypoint-fix17-proof.mjs`,
`waypoint-fix17-learns-mid.mjs`, `waypoint-fix17-base.mjs`.
19 DOM assertions, all PASS after one proof fix (below):

- **Race mid** (+0.7s): scaleX [0.97, 0.93, 0.84] — graph visibly last;
  counters caught at 24,845 / 682 / ~174. **Settled:** counter texts
  exact (incl. untouched "8/20"), fill widths = baseline to the pixel.
- **Learns mid** (fresh page, +0.9s): dashoffset 0.361 (line ~64%
  drawn), v1 opacity 1 (already plainly in), dots [1, 0.73, 0, 0],
  labels [1, 0.09, 0] — arriving in sequence. **Settled:** all 14
  labels exact, dashoffset 0, v2 points attribute unchanged, side
  cards at full opacity.
- **Load mid** (+1.2s): before card already at printed 126 / 0.61;
  after errors caught at 22 (DOM probe) / 17 (frame) counting DOWN,
  throughput at 27.3 / 28.7 climbing. **Settled:** values exact
  ["126","0.61","0","33.2"] — and the settled screenshot is
  byte-identical (same sha256) to the pre-change baseline capture.
- **Ingest/Install settled:** inview fired, all elements full opacity.
- **Reduced motion** (emulated): `html.ev` never added, bars at final
  width (transform: none), every number final — page identical to
  pre-change behaviour.
- **?state=resolved:** `ev` never added, hero snapped to 494, section
  stats final.
- **Hero regression:** flood frame (329 chips, 27,000, "Route it →")
  and resolved frame (fixedChipsInBody=0, pathrowChips=6, tok=494,
  "Route it again ↺") — identical to the Phase 14/15 end state.
  Footer untouched (no footer rules or markup changed).

Proof-fix note (honest): the first learns "mid" capture was actually
the settled state — scrolling to #race had already brought #learns
past the 35% threshold (its heading + chart top sit in the race
viewport), so it fired early and finished before its own capture.
That's correct real-world behaviour (a slow scroller sees it play);
the mid proof was re-shot on a fresh page jumping straight to #learns.

## Redeploy

/tmp/waypoint had been wiped by a VM replacement, so the bundle was
rebuilt preserving the live artifacts byte-for-byte: the /console page
was fetched from the live site (3,131 B, exactly the Phase 15 page) and
its three captures (console-run/graph/evidence.png) downloaded from
the live URLs; new index.html copied from the repo. Re-linked to the
existing `waypoint` project and deployed:
`vercel deploy --prod --yes --scope aayushi-team` →
https://waypoint-nine-iota.vercel.app — curl-verified `/` 200
(59,421 B, byte-identical to the new local file; contains `lv2line`,
the `html.ev` rules and the Phase 17 script), `/console` 200
(3,131 B), console image 200.

## Environment notes

The app server on :8077 was down at phase start (another VM
replacement); restarted (`python3 app/server.py`) for the proof and
left running. The HydraDB node was NOT touched (freeze rule) — the
website proof does not depend on it. The headless shell still logs one
ERR_TUNNEL_CONNECTION_FAILED for Google Fonts (VM egress limit, known
since Phase 14; real visitors load the webfont normally).
