# PHASE 7 LOG — Waypoint becomes a sellable product

Goal: answer the GTM half of the rubric ("who wants it, and can you pitch
it as a product people pay for") with product form, not just pitch text:
a customer must be able to bring their OWN tool catalog, install
Waypoint, and route through it the same day. The Phase 1–6 engine was
not replaced; it gained a front door, a buyable form, and packaging.

## Deliverable 1 — ingestion CLI (`app/ingest.py`)

`python3 app/ingest.py <file-or-dir> [--server NAME]` ingests MCP
tools/list-shaped JSON into the live graph, mirroring seed.py's write
patterns exactly (nodes: UNWIND + MERGE on id + SET; edges: UNWIND +
CREATE, which this DB dedupes on src/dst/type) — so ingestion is
idempotent by construction and verified so below.

- Type derivation from JSON Schema (deterministic): input property →
  `$ref` tail | array → element type + "List" | inline object →
  property name | `format` → format name | scalar →
  String/Integer/Number/Boolean. Output → outputSchema `title` |
  `$ref` | single-property object → that property's type | otherwise
  `<Tool>Output`.
- Scopes: the tool's own `scopes` list if present, else `<server>:use`.
- Tokens: `catalog.est_tokens` (same estimator as the benchmark
  catalog). Node ids for ingested data live in high bands (Tool
  100000+, DataType 200000+, Scope 300000+, MCPServer 400000+) and can
  never collide with the seeded catalog's ids.
- Marking: ingested tools carry `Tool.source='ingested'` and
  `core=True` (they are chain-bearing; find_tools routes the core
  layer). The seeded catalog has no `source` property, so the two stay
  distinguishable everywhere counts are displayed.

## Deliverable 2 — a real ingestion run (`examples/real-mcp/`)

Faithful transcriptions of the two official MCP reference servers —
tool names, input properties and required fields follow the published
servers; shared `$defs` (FilePath/TextContent, Entity/Relation) type the
cross-tool data flow, outputSchema gives the structured form of what
the servers return, and scopes are Waypoint-added (fs:read/fs:write,
memory:read/memory:write):

- **filesystem** — 14 tools (read_file, read_text_file, read_media_file,
  read_multiple_files, write_file, edit_file, create_directory,
  list_directory, list_directory_with_sizes, directory_tree, move_file,
  search_files, get_file_info, list_allowed_directories)
- **memory** — 9 tools (create_entities, create_relations,
  add_observations, delete_entities, delete_observations,
  delete_relations, read_graph, search_nodes, open_nodes)

Graph counts (live DB, `results/ingest-real.json`): Tool 329 → **352**,
DataType 55 → 80, Scope 25 → 29, MCPServer 12 → 14; edges HOSTED_BY
+23, INPUT_TO +29, OUTPUT +23, REQUIRES_SCOPE +23. Second ingestion run:
**0 new tools, counts unchanged — idempotent.**

Live routing over the real catalog (roles added to tasks.py ROLES:
fs_agent, fs_reader, memory_agent — benchmark tasks untouched):

- r1 (FilePath → WriteFileOutput, fs_agent): **[read_file, write_file]**
  — a real two-hop copy chain, 230 tokens.
- r2 (FilePath → FilePathList, fs_agent): **[list_allowed_directories]**,
  110 tokens.
- r3 (String → KnowledgeGraph, memory_agent): **[search_nodes]** via
  native MSpaths, 122 tokens.
- Refusal on real tools: r1 as **fs_reader** → REFUSED at `write_file`,
  missing scope `fs:write`. Correct.

## Deliverable 3 — Waypoint as an MCP server (`app/mcp_server.py`)

Stdlib-only stdio MCP server (newline-delimited JSON-RPC 2.0):
initialize, notifications/initialized, tools/list, tools/call, ping;
parse errors → -32700, unknown method → -32601, unknown tool → -32602,
tool exceptions returned as isError results. stdout carries JSON-RPC
only; logging goes to stderr. The three tools mirror meta_tools'
signatures: find_tools{start_type, goal_type, role, entity_name?},
resolve_entity{name}, report_outcome{chain, success}.

Proof (`app/prove_mcp.py` → `results/mcp-server-proof.txt`, full
transcript): initialize ok; tools/list = the 3 meta-tools; find_tools
(CompanyName → SentMail, finance_agent, Acme Corp) returned the exact
t03 chain at 494 tokens; resolve_entity('Acme Corp') → CustomerRef;
report_outcome wrote 5 CO_USED_WITH edges. All assertions pass.

## Deliverable 4 — packaging

- **PRODUCT.md** (new): one-line hook, buyer, problem in buyer
  language, what ships (MCP server + ingestion CLI + inspector console,
  self-hosted on HydraDB), 3-step install, pricing (per-1M-resolutions
  usage + per-seat governance tier, from PITCH.md), honest limits.
- **README.md**: top restructured into product form — Install (seed
  the demo catalog OR ingest your own) and "Use it from your agent"
  (MCP config snippet + the three tools) now precede the existing
  benchmark/learning/load evidence, which is unchanged; no verified
  number was deleted or altered.
- **PITCH.md**: added a "Product form" section — ships as MCP server +
  ingestion + console; a customer is live the same day; in-repo proofs
  cited.
- **Console**: `/api/graph` counts are now source-scoped (benchmark
  catalog stays exactly 329 / 41 core / 288 distractors, plus a separate
  `ingested_tools: 23`), and the top bar gained one chip — "ingested
  real: 23" — fed by that count. No backend routes were added.

## The regression I hit — and the fix (read this before trusting tiering)

The first post-ingestion `run_phase2.py` came back **19/20**: t20
flipped from [search_drive, summarize_doc, send_email_text] to the
structurally isomorphic [search_drive, get_file, send_email]. Both
chains are type-valid and equal-cost (0 supplied, 3 tools); the ground
truth encodes the task's intent ("email the SUMMARY"), which the type
system cannot see. Pre-ingestion, the tie was decided by Dijkstra heap
order over the 329-tool search space; adding 23 tools' worth of
suppliable-type state pushes flipped it. Diagnosis was verified piece
by piece (type vocabularies are disjoint; the entity-ref closure is
unchanged; token totals actually favour the wrong chain, 246 vs 248,
so a token tiebreak was rejected).

Fix — **tiered routing** in meta_tools.find_tools (documented in its
docstring): tier 1 searches the curated catalog only (core,
non-ingested); tier 2 widens to all chain-bearing tools and runs only
when tier 1 has no chain. A tier-1 chain — including a permission
refusal — is final. Tier 1 therefore reproduces the shipped catalog's
resolution bit-for-bit, and curated-before-ingested is also the
product's stated priority order. Two supporting changes:

- **Tier skip**: a tier with no producer of the goal type is skipped
  outright (a chain's last tool must produce the goal). This makes the
  common tier-1 miss instant.
- **Resolver exhaustion guard**: tiering exposed a latent blow-up —
  for an unreachable goal the resolver's Dijkstra must exhaust a
  combinatorial state space (it OOM-killed a test process at ~6 GB).
  The search now runs with a 20,000-expansion budget and, if tripped,
  retries inside the goal cone (tools whose produced types can reach
  the goal), which is sound and complete for reachability. Unreachable
  goals now answer in milliseconds via the tier skip; the budget+cone
  path bounds the produced-but-unreachable case.

## Regression gate (after all changes, live DB)

- `app/run_phase2.py`: **chain accuracy 20/20 (set and exact order),
  refusals 3/3, avg tokens 253.7, avg round trips 7.35, methods
  13 MSpaths / 7 resolver** — every headline number identical to the
  Phase 3 record.
- `examples/real-mcp/prove.py` re-run under the tiered engine: same
  chains, same refusal, idempotency pass.
- `app/prove_mcp.py` re-run: all assertions pass.
- Demo server restarted on the new code: page 200; `/api/graph` counts
  {total 329, core 41, distractors 288, ingested 23}; live POST t03 →
  exact chain, 494 tokens; t04 as support_agent → refused at
  void_invoice / payments:admin.

## Honest gaps

- **Slow path**: a goal that IS produced inside a tier but unreachable
  through satisfiable chains can burn the 20k-expansion budget
  (seconds) per tier before the cone retry answers. Produced-goal and
  unproduced-goal misses — the common cases — are fast.
- **Transcription layer**: the reference servers return plain text for
  several tools; the outputSchema structured forms and `$defs` typing
  in examples/real-mcp are Waypoint's reasonable-schema layer on top of
  the faithful names/properties/required fields, and scopes are
  Waypoint-added. Traversal quality follows schema quality (stated in
  PRODUCT.md).
- **seed.py verify()** counts ALL Tool nodes, so run against the
  combined graph it would report 352 vs its 329 expected. The seeded
  catalog itself is untouched (data/tools.json unchanged; run_phase2
  reproduces it exactly) — the verify total is a display artifact of
  the combined graph, noted rather than hidden.
- **MCP server surface**: stdio only (no HTTP transport), no auth —
  it inherits the MCP client's trust boundary, like the reference
  servers. Single-node HydraDB limits from PRODUCT.md/README stand.
- learning.py needed a one-line signature update
  (producible_closure now takes the key set); its recorded results are
  static artifacts and were not re-run.
