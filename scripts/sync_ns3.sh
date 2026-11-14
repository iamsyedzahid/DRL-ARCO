#!/usr/bin/env bash
# Copy the scenario into ns-3's scratch folder. Run again after editing any C++ file,
# then rebuild with: (cd "$NS3_HOME" && ./ns3 build drl-arco)
# Usage: bash scripts/sync_ns3.sh [ns3-home]     (default: $NS3_HOME)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-${NS3_HOME:?Set NS3_HOME or pass the ns-3 folder as an argument}}"

mkdir -p "$TARGET/scratch/drl-arco"
cp "$REPO_DIR"/ns3/scratch/drl-arco/*.cc "$REPO_DIR"/ns3/scratch/drl-arco/*.h \
    "$TARGET/scratch/drl-arco/"
echo "copied scenario to $TARGET/scratch/drl-arco"
