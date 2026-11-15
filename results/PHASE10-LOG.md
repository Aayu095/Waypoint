# Phase 10 — installable by a stranger, cold-proven

Date: Sun 2026-11-15 (IST). Goal: a buyer/judge cloning this repo reaches a
running product by following the README alone — no knowledge that lives
only in our heads.

## Deliverables

| File | What it is |
|---|---|
| `setup.sh` | One-time machine prep (apt → rustup/Rust 1.99.0 → just → HydraDB clone @ pinned commit → LAGraph → `just build-mcp`). Every step guarded/idempotent. |
| `run.sh` | Prepared machine → running product: node up (store = `./data/store`, override `WAYPOINT_STORE`), seed, ingest, app on :8077, prints the live line. |
| `Dockerfile` | App image (python:3.12-slim, the stdlib app). **UNTESTED** — see Docker status. |
| `docker-compose.yml` | hydradb (published image) + app. **UNTESTED**, header says so. |
| `.dockerignore`, `.gitignore` | Store/cache/run dirs and the docker token kept out of builds/commits. |
| `README.md`, `PRODUCT.md` | Install/Quickstart rewritten to the exact scripted path (3 steps). All verified numbers and evidence sections untouched. |

The install path a stranger now follows:

```bash
./setup.sh   # once: packages, Rust, built HydraDB (clone lands in ../hydradb)
./run.sh     # node + catalogs + app
# http://localhost:8077 (website) · http://localhost:8077/console (product)
```

## State of the machine when this phase started (all verified, none assumed)

- The whole live stack was **down**: a VM replacement had killed the node
  (pid file stale) and the app server, and wiped part of the apt-installed
  system — `graph-node` failed to start with
  `libgraphblas.so.7: cannot open shared object file`.
- Missing apt packages: `clang`, `libclang-dev`, `libcypher-parser-dev`,
  `libgraphblas-dev` (and the GraphBLAS runtime). Present: rustup, cargo,
  `just` 1.59.0, the HydraDB checkout (HEAD `9166374`, v0.4.0, target/
  intact at 6.3 GB), the original store on disk (792 KB, intact).
- Package lists were empty post-replacement; `apt-get update` fetched
  71.1 MB in 10m38s (111 kB/s mirror). `libgraphblas7` is the runtime
  package name on Ubuntu 24.04.

## setup.sh — what was actually re-run vs what rests on the record

Ran live: `HYDRA_SRC=~/workspace/hydradb-prep/hydradb
LAGRAPH_PREFIX=~/workspace/hydradb-run/lagraph bash setup.sh` → **exit 0**.

- Step 1 (apt): **executed for real** — installed the 4 missing packages
  (+ dependencies, incl. clang 18 and the GraphBLAS runtime). A
  lists-freshness guard was added during this phase: `apt-get update`
  runs only when the lists are stale (>24h) or absent, so a fresh machine
  still gets its update and re-runs stay fast.
- Step 2 (rustup): guard path executed — already installed, toolchain
  1.99.0 confirmed active (`rustc 1.99.0`).
- Step 3 (just): guard path executed — 1.59.0 already present.
- Step 4 (clone): guard path executed — checkout present, HEAD already at
  the pinned commit `916637477f3f34766b4905b270bd4292109d77e6`; the
  `git clone` itself was **not** re-run (it rests on the documented remote
  `https://github.com/hydra-db/hydradb.git`). `just native-check` ran and
  passed (cypher-parser + libgraphblas visible).
- Step 5 (LAGraph): guard path executed — `liblagraph.a` already built.
  The from-source build itself was **not** redone; it is recorded in
  `~/workspace/hydradb-run/BUILD-LOG.md` (~12 s via the repo's own
  `scripts/install_lagraph.sh`).
- Step 6 (build): guard path executed — `graph-node` binary present
  (669,689,056 bytes), build skipped. The full cargo build was **not**
  redone; it is recorded in the BUILD-LOG (first link failed on
  `-llagraph`, fixed by LAGraph, rebuild exit 0).

So: setup.sh's logic, guards, and apt step are live-verified; the three
heavy one-time productions (clone, LAGraph compile, full Rust build) rest
on the original bring-up record, exactly as the phase brief allowed.

## Baseline restored (before touching anything else)

`bash ~/workspace/hydradb-run/start-node.sh` + app server → health
`{"status":"ok"}`, **352 tools / 23 ingested** in the original store,
`POST /api/find_tools` t03 → exact 6-tool chain, **494 tokens**. The
original store survived the VM replacement untouched.

## Cold-start proof (the point of the phase)

Live stack stopped (node + app killed; ports 18443/19091/8077 confirmed
down), then:

```
HYDRA_SRC=~/workspace/hydradb-prep/hydradb \
WAYPOINT_STORE=~/workspace/waypoint/.cold-proof/store \
bash run.sh        → exit 0
```

Step-by-step results from that single run:

1. **Node from an empty store** — ready (pid 5617), `health: ok`.
2. **Seed** — seed.py's own DB-queried verify: `nodes Tool: db=329
   expected=329`, all 5 node labels and 6 edge types `[OK]`,
   **SEED VERIFY: PASS**.
3. **Ingest** — `filesystem: 14 tools (14 new)`, `memory: 9 tools
   (9 new)`, `tools: 329 -> 352 (ingested total: 23)`.
4. **App** — started (pid 5659), run.sh printed
   `Waypoint is live: http://localhost:8077 (website) · /console (product)`.

Independent verification against the scratch stack (not run.sh's own
output): direct DB query **352 tools / 23 ingested**; `POST
/api/find_tools` t03 → chain `[lookup_customer, list_invoices,
get_invoice, invoice_pdf, find_contact, send_email]`, **494 tokens**;
`GET /` → **200** (website title); `GET /console` → **200** (console
title).

### Safety guard, proven

With the original stack running, `run.sh` against a scratch store exits
1 with: *"a HydraDB node is already answering on :19091 but was not
started by this run.sh … It may be serving a different store — stop it
first."* It refuses to seed/ingest into a store it doesn't own.

### Idempotency, proven

Scratch store, two consecutive `run.sh` invocations, both exit 0.
Second run: `node already running — reusing` · `catalog already loaded
(352 tools) — skipping seed` · `tools: 352 -> 352 (ingested total: 23)`
(0 new) · `app already answering on :8077 — reusing`.

(One design note this forced: seed.py's verify counts **every** Tool
node, so re-running it after ingestion would report a false MISMATCH.
run.sh therefore seeds only when the catalog is absent or partial —
seed's writes are idempotent MERGEs — and skips with a message when the
catalog is already loaded.)

### Teardown + restore

Scratch node/app killed via the pid files in `.cold-proof/store.run`,
scratch dir deleted. Original stack restarted
(`start-node.sh`, node pid 5930, + app server) and re-verified:
**original store intact — 352 tools / 23 ingested**, t03 exact chain /
494 tokens, health ok, ports 17687/18443/19091/8077 all listening.
**Both servers are left running.**

## Docker status: UNAVAILABLE here, compose UNTESTED

`docker: command not found` on this VM — nothing about the Docker path
could be executed. What the repo's own docs establish:

- The engine publishes `ghcr.io/hydra-db/hydradb` — named in
  `charts/hydradb/values.yaml` and `examples/values-eks.yaml`, published
  by `.github/workflows/container.yml` with semver tags; Chart
  `appVersion` is `0.4.0`, so the compose pins
  `ghcr.io/hydra-db/hydradb:0.4.0`.
- The image's runtime stage is `ENTRYPOINT ["graph-node"]`, configured
  by the same `GRAPH_*` env vars run.sh sets; the compose mirrors
  run.sh's env (container paths: store volume at `/data`, cache at the
  image's own `/var/cache/slatedb`).
- The app service uses `network_mode: host` because `app/client.py`
  talks to the node at a fixed `localhost:18443`, and mounts the shared
  token file at the fixed path client.py reads.

`docker-compose.yml`, `Dockerfile`, `README.md`, and `PRODUCT.md` all
mark this path **UNTESTED** and name the scripted path as the tested
one. Nothing anywhere claims it works.

## Honest gaps

- **client.py's fixed token path** (`~/workspace/hydradb-run/token.txt`)
  is a wart this phase had to design around, not fix: client.py was
  off-limits. run.sh creates that file and points the node at it; README
  and run.sh both document it plainly. A future cleanup would make the
  token path an env var in client.py.
- **setup.sh from absolute zero** (bare Ubuntu: rustup install, full
  clone, LAGraph compile, full cargo build) was not re-executed
  end-to-end — see the step table above for exactly which parts were
  re-run and which rest on `~/workspace/hydradb-run/BUILD-LOG.md`.
- **run.sh's defaults assume the sibling layout** setup.sh creates
  (`../hydradb`). On this VM the proof ran with `HYDRA_SRC` pointed at
  the existing checkout — the documented knob, used as documented.
- **Timing**: with the binary built, a cold run.sh (empty store →
  verified product) took seconds on this box. A stranger's first
  setup.sh is dominated by apt + the Rust build: budget 30–60 min and
  ~10 GB disk, as the script header and README say.
