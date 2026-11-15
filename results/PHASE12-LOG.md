# PHASE 12 — Console spacing / polish pass (2026-11-15)

Aashi's verdict on the Phase 11 console screenshot: cramped — no proper spacing,
panels and borders running right up to the laptop screen edges. This pass is
**visual spacing only** in `app/demo.html`: no content, copy, colors, fonts,
panel order, or JS behavior changed. Website (`/`) untouched.

## What changed (before → after)

### 1. Outer frame — nothing touches the viewport edge anymore
- `body`: no padding → **`padding:19px 24px`** (a real outer margin ring on all
  four sides; the dot-grid background shows through it like a desk mat).
- `#topbar`: `border-bottom` only → **full `1px solid var(--line)` border**;
  height 47px → 50px; side padding 16px → 18px.
- `#shell`: no border → **`border:1px solid var(--line); border-top:none`** —
  topbar + shell now read as ONE framed console floating inside the margin,
  header aligned with the columns below.
- `.chip` padding 5px 9px → 6px 10px.

### 2. Gutters — columns and stacked sections no longer touch
- RUN stage: column gap 14px → **18px**; stage padding 14px sides → **18px**.
- All RUN-view sections now share one **18px inset**: `#resultstrip` margin
  0 14px → 0 18px; `#strips` padding sides 14px → 18px, column gap 14px → 16px;
  `#agentfeed` margin 0 14px 14px → 0 18px 18px.
- Vertical rhythm stage → result strip → bento strip → agent feed: ~14–16px
  bands throughout (stage bottom padding, strips top/bottom padding, feed's
  18px bottom margin before the frame border).
- Evidence view: padding 14px → **20px**, panel gap 14px → **16px**,
  `.evrow` gap 14px → 16px.

### 3. Inner padding — consistent ~16–18px inside panels
- `.panehead` 9px 12px 7px → 11px 16px 9px · `.winhead` → 11px 16px 9px ·
  `.winfoot` → 11px 16px · `#rail-right .sect` 9px 12px → 12px 16px ·
  `.evpanel` 13px 16px → 16px 18px · `.strip` 10px 13px → 12px 15px ·
  `#chainbox` → 12px 16px 8px · `#meterbox` → 10px 16px 14px ·
  `#graphlegend` inset 8/10px → 12/14px.
- Task rows: `.trow` padding 7px 12px → **9px 14px**.
- Role area: `#rolebox` 10px 12px → **14px 16px**; `#pills` margin 7px 0 10px →
  9px 0 12px, gap 5px → 6px; `.pill` 4px 8px → 5px 9px; `#runbtn` padding 11px →
  12px; `#runnote` margin-top 7px → 9px.
- Agent feed: `.afrow` padding 3px 0 → 4px 0 **+ `line-height:1.5`** (was
  default); feed head margin-bottom 5px → 7px.
- Inspector rows: `.kv` 2.5px → 3.5px vertical; `.srow` 3px → 4px.
- Nav rail: padding 12px 8px → 14px 10px, gap 8px → 10px; `.navbtn` padding
  9px 6px 7px → 10px 8px 8px.

### 4. Fit fix found during proof (spacing-only trims)
First t03 screenshot at 1440×900: the completed run's 6th chain card
(`send_email`) sat at/past the routed frame's bottom edge — the new frame +
gutters consume ~60px of vertical budget, and the completed state must show
the whole chain. A geometry probe (puppeteer-core, webfonts loaded) measured
the overflow at exactly 2px. Fixed with micro-trims, all still at/above the
original breathing room where it matters:
- `.tcard` padding 9px 11px → 6px 11px, margin-bottom 6px → 4px
- `.winframe` padding 14px → 11px (first tried 12px; settled at 11px)
- `.afrow` 5px → 4px vertical, `#agentfeed` padding 12/11px → 11/10px,
  `#stage` bottom padding 14px → 11px, `#resultstrip` 13px → 12px,
  `#strips` basis 124px → 120px, `body` vertical padding 20px → 19px
- **Re-probed: last card bottom sits 12px INSIDE the frame** (frame 121→386,
  card 337→374), all 6 cards `visible:true` under loaded-font metrics.

## Deliberately left alone
- **Stage panel heights (task item 4):** the wincols have no explicit
  min-height to reduce — their height is `#stage{flex:1}` growth inside a
  fixed-height column. Capping the stage would not remove the idle void, only
  move it below the agent feed, and would behave inconsistently across
  viewport heights. The WITH panel's empty state is vertically centered by
  design, and the run animation appends cards into that flex space. Left as
  is; the added frame/gutter budget already trims ~60px of stage height.
- **Flood "+274 more tools" chip:** a geometry probe shows it sits ~86px
  below the flood frame's fold at 1440×900. This is pre-existing, not a
  regression: the flood content height is unchanged by this pass, and the
  chip was already past the fold at this viewport before Phase 12 (the frame
  was ~60px taller; the chip ~86px past). The flood frame is
  `overflow:hidden` by design (a sample of the 352-tool preload); the chip
  appears at taller viewports — it is visible in Aashi's own 1600×1000
  screenshot from before this pass.
- `#strips` measured height is content-driven (~152px) despite its flex
  basis — pre-existing behavior, all strip content renders fully.

## Proof (all read by the agent, chrome-headless-shell, 1440×900)
- `results/shots/waypoint-spacing-idle.png` — margin ring visible on all four
  sides; gutters between columns and every stacked section; nothing clipped
  or overlapping; task pane scrolls by design.
- `results/shots/waypoint-spacing-t03.png` — deep link
  `?task=t03&role=finance_agent&run=1&instant=1`: full 6-card chain visible,
  **494 tok loaded · 98.2% saved vs preload**, result line + stats correct.
- `results/shots/waypoint-spacing-evidence.png` — `?view=evidence`: panels
  inset 20px inside the frame, 16px gaps, race/learning/load/ingestion all
  render (panel 08 below the scroll fold, as designed).
- Backend untouched: `POST /api/find_tools` t03 → exact 6-tool chain,
  `tokens_loaded: 494`, `refused: false`. Console HTTP 200, HydraDB health 200.
- Both servers left running (app `server.py` on :8077 + `graph-node`);
  **the HydraDB node was NOT restarted** (freeze rule); the app server needed
  no restart — it serves demo.html from disk per request.
