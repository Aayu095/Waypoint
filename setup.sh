#!/usr/bin/env bash
# Waypoint — setup.sh: one-time machine preparation.
#
# What it does (mirrors the bring-up recorded in results/PHASE10-LOG.md):
#   1. apt system packages (build tools, clang, cypher-parser, GraphBLAS)
#   2. rustup + Rust toolchain 1.99.0 (the pin in HydraDB's rust-toolchain.toml)
#   3. `just` (via cargo — Ubuntu's apt just is too old for HydraDB's justfile)
#   4. clones HydraDB (https://github.com/hydra-db/hydradb.git) at the pinned
#      commit 916637477f3f34766b4905b270bd4292109d77e6 (v0.4.0)
#   5. builds LAGraph from source via HydraDB's own scripts/install_lagraph.sh
#      (Ubuntu ships no LAGraph package; graph-node will not link without it)
#   6. builds the HydraDB binaries (`just build-mcp` -> target/debug/graph-node)
#
# How long: apt took ~15 min on a slow mirror during the original bring-up;
# the Rust build is the long pole (tens of minutes on 2-4 cores). Budget
# 30-60 minutes for a first run on a fresh machine.
# Disk: ~10 GB free — the HydraDB target/ directory alone is ~6.5 GB here,
# plus ~2 GB of Rust toolchains under ~/.cargo and ~/.rustup.
# OS: Ubuntu 24.04 (apt-based). Every step is guarded: if it is already
# done, it is skipped, so re-running this script is cheap and safe.
# Set FORCE_BUILD=1 to rebuild HydraDB even if the binary already exists.
#
# Layout knobs:
#   HYDRA_SRC       where the HydraDB checkout lives
#                   (default: ../hydradb, next to this repo)
#   LAGRAPH_PREFIX  where the static LAGraph build goes (default: ~/lagraph)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HYDRA_SRC="${HYDRA_SRC:-$REPO_ROOT/../hydradb}"
HYDRA_REPO="https://github.com/hydra-db/hydradb.git"
HYDRA_COMMIT="916637477f3f34766b4905b270bd4292109d77e6"
LAGRAPH_PREFIX="${LAGRAPH_PREFIX:-$HOME/lagraph}"
RUST_TOOLCHAIN="1.99.0"

export PATH="$HOME/.cargo/bin:$PATH"

step() { printf '\n=== %s ===\n' "$*"; }

# --- 1. system packages -----------------------------------------------------
step "1/6 system packages"
APT_PACKAGES=(build-essential clang libclang-dev cmake pkg-config \
              libcypher-parser-dev libgraphblas-dev python3-venv curl git)
missing=()
for pkg in "${APT_PACKAGES[@]}"; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ "${#missing[@]}" -eq 0 ]; then
  echo "all ${#APT_PACKAGES[@]} packages already installed — skipping apt"
else
  echo "installing: ${missing[*]}"
  if [ -n "$(find /var/lib/apt/lists -name '*_Packages' -mmin -1440 2>/dev/null | head -1)" ]; then
    echo "apt package lists are fresh (<24h) — skipping apt-get update"
  else
    sudo apt-get update
  fi
  sudo apt-get install -y "${missing[@]}"
fi

# --- 2. rustup + toolchain --------------------------------------------------
step "2/6 rustup + Rust $RUST_TOOLCHAIN"
if [ ! -x "$HOME/.cargo/bin/rustup" ]; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
else
  echo "rustup already installed — skipping"
fi
if ! rustup toolchain list | grep -q "^${RUST_TOOLCHAIN}"; then
  rustup toolchain install "$RUST_TOOLCHAIN"
fi
if [ "$(rustup show active-toolchain | awk '{print $1}')" != "${RUST_TOOLCHAIN}-x86_64-unknown-linux-gnu" ]; then
  rustup default "$RUST_TOOLCHAIN"
fi
rustc --version

# --- 3. just ----------------------------------------------------------------
step "3/6 just"
if command -v just >/dev/null 2>&1; then
  echo "just $(just --version) already installed — skipping"
else
  cargo install just --locked
fi

# --- 4. HydraDB clone at the pinned commit ----------------------------------
step "4/6 HydraDB checkout ($HYDRA_SRC)"
if [ ! -d "$HYDRA_SRC/.git" ]; then
  git clone "$HYDRA_REPO" "$HYDRA_SRC"
else
  echo "checkout already present — skipping clone"
fi
if [ "$(git -C "$HYDRA_SRC" rev-parse HEAD)" != "$HYDRA_COMMIT" ]; then
  git -C "$HYDRA_SRC" fetch origin "$HYDRA_COMMIT" 2>/dev/null \
    || git -C "$HYDRA_SRC" fetch origin
  git -C "$HYDRA_SRC" checkout "$HYDRA_COMMIT"
fi
echo "HydraDB HEAD: $(git -C "$HYDRA_SRC" log -1 --format='%h %s')"

# Sanity: the native libraries HydraDB links against (repo's own check).
( cd "$HYDRA_SRC" && just native-check )
echo "native-check OK (cypher-parser + libgraphblas visible)"

# --- 5. LAGraph -------------------------------------------------------------
step "5/6 LAGraph (static, built from source)"
if [ -f "$LAGRAPH_PREFIX/lib/liblagraph.a" ]; then
  echo "liblagraph.a already built at $LAGRAPH_PREFIX — skipping"
else
  mkdir -p "$LAGRAPH_PREFIX/tmp"
  # The install script uses mktemp; give it room on the home filesystem.
  TMPDIR="$LAGRAPH_PREFIX/tmp" bash "$HYDRA_SRC/scripts/install_lagraph.sh" "$LAGRAPH_PREFIX"
fi

# --- 6. build HydraDB -------------------------------------------------------
step "6/6 build HydraDB (just build-mcp)"
if [ -x "$HYDRA_SRC/target/debug/graph-node" ] && [ "${FORCE_BUILD:-0}" != "1" ]; then
  echo "graph-node binary already built — skipping (FORCE_BUILD=1 to rebuild)"
else
  ( cd "$HYDRA_SRC" && LAGRAPH_LIB_DIR="$LAGRAPH_PREFIX/lib" \
      CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}" just build-mcp )
fi
ls -la "$HYDRA_SRC/target/debug/graph-node"

step "done"
echo "Machine prepared. Start the product with:  ./run.sh"
