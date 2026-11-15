# PHASE 9 — Waypoint product website (site/index.html)

Standalone single-file static site. Opens via file://, no build, no backend.
Only external dependency: Google Fonts (Space Grotesk + JetBrains Mono) with
system fallbacks. Phase 8's app/demo.html and app/server.py were NOT touched.

## The hero mechanic

- On load, the hero is flooded with **all 329 real tool names** from
  `data/tools.json` (injected verbatim into the page's TOOLS array), rendered
  as small dim chips with a slow per-chip drift — the agent's drowned context.
- Headline: "Your agent loads 329 tools…" then "…to send *one email.*" fades in.
- Task bar (pre-filled with the t03 task text) + orange "Route it →" button.
  Auto-routes ~1.5 s after load; replayable ("Route it again ↺" resets the
  flood and re-routes).
- On routing: the 323 non-chain chips fade/scale/blur out with staggered
  delays; the six t03 chain chips (lookup_customer, list_invoices,
  get_invoice, invoice_pdf, find_contact, send_email) FLIP-glide out of the
  flood into a clean centred path with a connecting line, lighting orange in
  sequence. Token counter ticks 27,000 → 494. Headline resolves to
  "Waypoint. / Agents pull only what the task needs." + one sub-line +
  CTAs ("Open the product →" href="./console" with an integration comment,
  "See the evidence ↓").
- `?state=flood` holds the flooded state; `?state=resolved` jumps straight to
  the end state; `prefers-reduced-motion` also jumps to resolved.

## Number sources (every figure read from the real files)

| Figure | Source |
|---|---|
| 329 tools, all chip names | data/tools.json (329 entries, injected verbatim) |
| 27,000 tok preload · 823 tok TF-IDF · 8/20 full chain · ~254 tok graph · 20/20 exact | results/benchmark.json (arm_a/b/c; means 823.2 / 253.7) |
| 494 tokens, t03 chain of 6 | results/benchmark.json arm_c per_task t03 (tokens_loaded 494) |
| 106× fewer tokens | derived: 27,000 / 253.7 ≈ 106 |
| v1 curve 0.40 → 0.35 → 0.35 → 0.35 | results/learning.json pass_accuracies |
| v2 curve 0.85 → 0.90 → 0.95 → 0.95; +1/−1 outcome rule | results/learning2.json |
| Load BEFORE: 126 errors / 150 calls, 0.61 calls/s, 50 agents | results/loadtest.json summary (0.609) |
| Load AFTER: 0 errors, 33.2 calls/s; 54× | results/loadtest2.json, 50-agent run (33.202); 33.2/0.61 ≈ 54 |
| Ingestion: filesystem 14 tools, memory 9 tools | results/ingest-real.json ingestion.per_server |
| read_file → write_file, 230 tok; search_nodes 122 tok; read-only role refused at write_file (fs:write) | results/ingest-real.json tasks r1/r3 + refusal |
| MCP config snippet | README.md "Use it from your agent" — copied exactly |
| Pricing chip "per 1M tool resolutions · governance tier per seat" | PRODUCT.md Pricing (per million resolutions; governance tier per-seat) |

Race bars are log-scale (widths ∝ log10 of tokens: 27,000 → 100%,
823 → 65.8%, 254 → 54.2%) and the page says so on the card — linear widths
would make the graph bar ~1% wide and unreadable.

## Design decisions

- Console brand family, website rhythm: #0a0908, dot grid, 1px borders
  rgba(255,255,255,.08), Space Grotesk display (~80 px hero), JetBrains Mono
  chips/labels, #ff4d00 reserved for state/CTA/key numbers.
- Permissions appear exactly once, as a small "✕ STOPPED" note in the
  ingestion section — supporting evidence, not a headline, per the brief.
- No testimonials, no logos, no lorem. The failed learning v1 is shown
  deliberately ("first attempt — failed, kept honest").

## Bugs found during verification (and fixed)

1. **Late webfont swap shifted layout after FLIP measurement**, stranding
   the gliding chips ~50 px off target (overlapping the readout).
   Fix: routing is gated on `document.fonts.ready`; the token readout also
   moved below the path stage so it can never collide with the chip row.
2. **CSS specificity**: `body.routed .chip.chain` (0,3,1) silently beat
   `.chip.chain.lit` (0,3,0), so lit chips never filled orange.
   Fix: selector raised to `body.routed .chip.chain.lit`.
3. **Virtual-time frame races**: headless screenshots caught mid-transition
   frames. Fix: `?state=` modes run in a "snap" mode (all transitions and
   animations disabled, end-state applied fully synchronously). In snap
   mode the path is rendered as a plain in-flow row inside the stage —
   no measurement, no transforms — so the end state is deterministic.
   The animated FLIP path is unchanged for real visitors.

## Verification

Screenshots (headless Chrome, 1440 px wide), all read and checked:
- results/shots/waypoint-site-flood.png (1440×1000, ?state=flood) — full
  chip flood, both headline lines, task bar, 27,000 counter. ✓
- results/shots/waypoint-site-resolved.png (1440×1000, ?state=resolved) —
  six orange chips on the connecting line, "494 · 6 tools loaded",
  caption, sub-line, CTAs. ✓
- results/shots/waypoint-site-full.png (1440×2600, ?state=resolved) —
  viewport capture; see gap note below. ✓ (hero)
- Sections 01–05 + footer additionally verified via a QA copy in /tmp with
  the hero height pinned (the deliverable itself untouched): race bars,
  learning SVG (both curves, correct values), before/after load cards,
  ingestion cards + refusal note, install code card + footer all render
  correctly with no overlaps.

## Honest gaps

- **waypoint-site-full.png shows only the hero.** The hero is
  min-height:100vh, so in a 2600 px-tall viewport it fills the whole
  capture and the sections sit below it. Sections were verified separately
  (above), but no single delivered screenshot shows the full page.
- **Browser used**: /usr/bin/google-chrome-stable does not exist on this VM
  and /opt/meta-chromium/chrome refuses to start ("Hatch WebGL domain
  policy is required"). Screenshots were taken with the Puppeteer-cache
  Chrome 156 binary (~/.cache/puppeteer/chrome/.../chrome).
- **Copy button not click-tested**: headless screenshot mode can't exercise
  the clipboard; the handler uses navigator.clipboard with an
  execCommand fallback and swaps the label to "Copied ✓".
- **Animated FLIP not frame-verified**: virtual-time headless frames are
  unreliable mid-animation; the state it lands on is the verified snap
  state, and the geometry fix (fonts.ready gating) removes the known
  offset cause. A human opening the file will see the full animation.
- Google Fonts needs network; offline, the page falls back to system
  fonts (layout holds — chip targets are measured after fonts.ready
  resolves or a 1.2 s timeout).
