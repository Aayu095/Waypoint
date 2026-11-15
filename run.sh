#!/usr/bin/env bash
# Waypoint — run.sh: from a prepared machine (see setup.sh) to a running
# product. Starts the HydraDB node, loads the catalogs, serves the app.
#
#   ./run.sh
#
# Layout knobs:
#   HYDRA_SRC      HydraDB checkout built by setup.sh
#                  (default: ../hydradb, next to this repo)
#   WAYPOINT_STORE HydraDB store directory
#                  (default: ./data/store inside this repo)
#                  The node's cache and pid/log files live beside it as
#                  <store>.cache and <store>.run, so a scratch store is
#                  fully self-contained (the cold-start proof uses this).
#
# Ports (fixed by the app): Bolt 17687 / HTTP 18443 / Admin 19091 for the
# node, 8077 for the website + console. Idempotent: a node/app already
# started by this script is reused, seed and ingest add nothing twice.
#
# One fixed path to know about: app/client.py reads the node's auth token
# from ~/workspace/hydradb-run/token.txt. This script creates that file on
# first run (chmod 600) and points the node at the same file, so the app
# and the node always agree on the token.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HYDRA_SRC="${HYDRA_SRC:-$REPO_ROOT/../hydradb}"
STORE_DIR="${WAYPOINT_STORE:-$REPO_ROOT/data/store}"
CACHE_DIR="${STORE_DIR}.cache"
RUN_DIR="${STORE_DIR}.run"
TOKEN_FILE="$HOME/workspace/hydradb-run/token.txt"
NODE_BIN="$HYDRA_SRC/target/debug/graph-node"
ADMIN="http://127.0.0.1:19091"
HTTP="http://127.0.0.1:18443"

export PATH="$HOME/.cargo/bin:$PATH"

step() { printf '\n=== %s ===\n' "$*"; }
die() { echo "run.sh: $*" >&2; exit 1; }

# --- preflight ---------------------------------------------------------------
[ -x "$NODE_BIN" ] || die "graph-node binary not found at $NODE_BIN — run ./setup.sh first (or set HYDRA_SRC)"
command -v python3 >/dev/null || die "python3 not found"
mkdir -p "$STORE_DIR" "$CACHE_DIR" "$RUN_DIR" "$(dirname "$TOKEN_FILE")"

# --- auth token (the file app/client.py reads) --------------------------------
if [ ! -s "$TOKEN_FILE" ]; then
  head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 43 > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "created node auth token at $TOKEN_FILE"
fi

# --- HydraDB node --------------------------------------------------------------
step "HydraDB node (store: $STORE_DIR)"
node_alive=0
if [ -f "$RUN_DIR/node.pid" ] && kill -0 "$(cat "$RUN_DIR/node.pid")" 2>/dev/null \
   && grep -qa graph-node "/proc/$(cat "$RUN_DIR/node.pid")/cmdline" 2>/dev/null; then
  node_alive=1
fi
if [ "$node_alive" = 1 ] && curl -fsS "$ADMIN/readyz" >/dev/null 2>&1; then
  echo "node already running (pid $(cat "$RUN_DIR/node.pid")) — reusing"
elif curl -fsS "$ADMIN/readyz" >/dev/null 2>&1; then
  die "a HydraDB node is already answering on :19091 but was not started by this run.sh (no live pid in $RUN_DIR). It may be serving a different store — stop it first."
else
  export CLOUD_PROVIDER=local LOCAL_PATH="$STORE_DIR"
  export GRAPH_NAMESPACE=local GRAPH_ID=default
  export GRAPH_CELL_ID=cell-0 GRAPH_CELLS=cell-0 GRAPH_DATA_PATH=data
  export GRAPH_ALLOW_PLAINTEXT=true GRAPH_AUTH_TOKEN_FILE="$TOKEN_FILE"
  export GRAPH_DATA_CACHE_BYTES=67108864 GRAPH_DATA_CACHE_DIR="$CACHE_DIR"
  export GRAPH_NODE_ID=node-0
  export GRAPH_BOLT_ADDR=127.0.0.1:17687 GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:17687
  export GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:17687
  export GRAPH_HTTP_ADDR=127.0.0.1:18443 GRAPH_ADMIN_ADDR=127.0.0.1:19091
  export RUST_MIN_STACK=33554432 RUST_LOG=info
  nohup "$NODE_BIN" >"$RUN_DIR/node.log" 2>&1 &
  node_pid=$!
  disown "$node_pid" 2>/dev/null || true
  echo "$node_pid" > "$RUN_DIR/node.pid"
  for _ in $(seq 1 90); do
    curl -fsS "$ADMIN/readyz" >/dev/null 2>&1 && break
    kill -0 "$node_pid" 2>/dev/null || { tail -20 "$RUN_DIR/node.log"; die "node failed to start (log: $RUN_DIR/node.log)"; }
    sleep 1
  done
  curl -fsS "$ADMIN/readyz" >/dev/null 2>&1 || { tail -20 "$RUN_DIR/node.log"; die "node did not become ready in 90s (log: $RUN_DIR/node.log)"; }
  echo "node ready, pid $node_pid (log: $RUN_DIR/node.log)"
fi
curl -fsS "$HTTP/healthz" | grep -q '"status":"ok"' || die "node health check failed on $HTTP/healthz"
echo "health: ok"

# --- catalogs -------------------------------------------------------------------
tool_count() {
  python3 - "$REPO_ROOT/app" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from client import run
print(run("MATCH (n:Tool) RETURN count(*) AS c")[0]["c"])
PY
}

step "demo catalog (seed)"
count="$(tool_count)"
if [ "$count" -eq 0 ]; then
  python3 "$REPO_ROOT/app/seed.py"
elif [ "$count" -lt 329 ]; then
  echo "partial catalog ($count tools) — completing the seed (its writes are idempotent)"
  python3 "$REPO_ROOT/app/seed.py"
else
  echo "catalog already loaded ($count tools) — skipping seed"
fi

step "real MCP catalogs (ingest: official filesystem + memory servers)"
python3 "$REPO_ROOT/app/ingest.py" "$REPO_ROOT/examples/real-mcp"
echo "tools in graph now: $(tool_count)"

# --- app server -------------------------------------------------------------------
step "Waypoint app (website + console on :8077)"
if curl -fsS -o /dev/null http://127.0.0.1:8077/ 2>/dev/null; then
  echo "app already answering on :8077 — reusing"
else
  nohup python3 "$REPO_ROOT/app/server.py" >"$RUN_DIR/app.log" 2>&1 &
  app_pid=$!
  disown "$app_pid" 2>/dev/null || true
  echo "$app_pid" > "$RUN_DIR/app.pid"
  for _ in $(seq 1 30); do
    curl -fsS -o /dev/null http://127.0.0.1:8077/ 2>/dev/null && break
    kill -0 "$app_pid" 2>/dev/null || { tail -20 "$RUN_DIR/app.log"; die "app failed to start (log: $RUN_DIR/app.log)"; }
    sleep 1
  done
  curl -fsS -o /dev/null http://127.0.0.1:8077/ || die "app did not answer on :8077 (log: $RUN_DIR/app.log)"
  echo "app ready, pid $app_pid (log: $RUN_DIR/app.log)"
fi
curl -fsS -o /dev/null http://127.0.0.1:8077/console || die "console did not answer on :8077/console"

echo
echo "Waypoint is live: http://localhost:8077 (website) · /console (product)"
