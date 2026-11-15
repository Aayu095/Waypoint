# PHASE 13 — Website motion/scroll fixes (2026-11-15)

Aashi opened the live site herself and reported three real defects that static
state captures had missed. All fixed in `site/index.html` only, proven in
motion and in scroll this time, and redeployed.

## 1 · Flood state didn't hold (auto-route at ~1.5s)

**Fix:** the flood now dwells **5,000 ms of visible time** (`DWELL_MS`) before
auto-routing — enough to read the headline and the 27,000 counter twice.
- Clicking "Route it" routes immediately at any time (route() cancels the dwell).
- "Route it again" now resets to the flood and re-arms the same 5s dwell
  (previously it re-routed after 420 ms).
- The clock **pauses while the hero is off-screen** (IntersectionObserver,
  threshold 0.25) or the tab is hidden (visibilitychange); it resumes with the
  remaining time when the hero returns. No unseen resolves.
- `prefers-reduced-motion` still goes straight to resolved; `?state=flood`
  and `?state=resolved` holds unchanged (verified below).

## 2 · Floating chip strip overlapped THE RACE section — ROOT CAUSE

**Mechanism:** in `route()` (animated path), the six chain chips were pulled
out of the flood, given `position:fixed` + `z-index:40`, appended to
`document.body`, and transformed to their landing spots for the FLIP glide —
**and never taken out of `position:fixed` afterwards.** Fixed elements are
anchored to the viewport, so the lit strip stayed on screen while the page
scrolled and covered THE RACE heading/subheading. (Snap mode never had the
bug: it renders the chips in-flow in `#pathrow` — which is why the static
`?state=resolved` captures always looked clean.)

**Fix (root cause, not a z-index tuck):** 1.9s after routing starts (glide
0.95s + stagger ≈ 1.2s, last chip lit ≈ 1.47s), a *settle* step hands the
chips to the in-flow `#pathrow` — the exact end state snap mode renders —
adds `body.snaproute` (which also swaps `#pathline` for the row's own
connecting line) and **removes the fixed copies from the DOM**. After the
settle, nothing hero-related is fixed or floating; the hero scrolls away like
any other section. A `routeGen` counter guards the settle against a replay
clicked mid-window (reset bumps the generation and cancels the pending
settle).

## 3 · The lit strip was too big

`body.routed .chip.chain`: font-size **12.5px → 10.5px** (−16%), padding
**8px 13px → 6px 11px**; chip height 30.5px → 24.5px (−20%). The strip now
reads as a result line. `#pathcap` top 56px → 50px to keep the same rhythm
under the slimmer chips; connecting line and glow unchanged. The FLIP
measures the chips after `body.routed` applies, so the glide and the settle
geometry (gap 40px, stage-centered) are unchanged and the settle swap is
pixel-aligned at both 1600×1000 and 1440×900 layouts.

## 4 · Closing

Footer verified rendering (wordmark line + pricing chip). Added the one
permitted sign-off line above it, in the site's voice:
"Waypoint — agents pull only what the task needs." (centered, dim, 16px).

## Proof (puppeteer, local server, 1600×1000 — every screenshot read by hand)

Scripts: `~/workspace/tools/pptr/waypoint-fix13-proof.mjs`,
`waypoint-fix13-dwell.mjs`, `waypoint-fix13-state.mjs`.

- `waypoint-fix13-flood3s.png` — at ~3s: pure flood, headline + "…to send one
  email." + 27,000 all readable, `routed=false`. ✓
- `waypoint-fix13-resolved8s.png` — resolved hero; DOM state at capture:
  `routed=true, snaproute=true, fixedChipsInBody=0, pathrowChips=6, tok=494`.
  Slimmer strip composes cleanly under the task bar. ✓
- `waypoint-fix13-scroll500.png` — the exact frame from Aashi's screenshot:
  THE RACE heading + "A vector store guesses similar tools…" **fully
  visible, zero overlap**; hero bottom scrolling away above it. ✓
- `waypoint-fix13-scroll900.png` / `scroll1300.png` / `scroll1700.png` —
  sections own the screen; no hero elements anywhere. ✓
- `waypoint-fix13-footer.png` — sign-off line + wordmark line + pricing chip
  all render. ✓
- Dwell behaviour (state assertions): hero scrolled away at ~1.2s → still
  unrouted at ~7.7s (paused); scrolled back → routed within the remaining
  dwell; "Route it again" → flood restored (unrouted); click during dwell →
  routed immediately. All four as specified. ✓
- `?state=flood` after 7s: unrouted ✓ · `?state=resolved`: routed + snaproute
  immediately ✓.

## Redeploy

Bundle rebuilt at `/tmp/waypoint`: fixed `index.html` at root + the previous
bundle's unchanged `/console` page and its three images; `.vercel` link kept.
`vercel deploy --prod --yes --scope aayushi-team` → production
https://waypoint-nine-iota.vercel.app — curl-verified `/` 200 and `/console`
200, and the served HTML contains the new sign-off line and `DWELL_MS = 5000`
(the headless shell cannot reach public URLs from this VM — ERR_TUNNEL is a
VM limit; curl + local captures are the verification).

No other files touched. Local servers left running; HydraDB node not restarted.
