#!/usr/bin/env bash
# Install ns-3.40 and the ns3-gym module, then build the DRL-ARCO scenario.
# Run inside Ubuntu 22.04 (native or WSL2), from the repository root.
# Usage: bash scripts/install_ns3.sh [install-dir]     (default: ~/ns-allinone)
set -euo pipefail

NS3_VERSION="3.40"
INSTALL_DIR="${1:-$HOME/ns-allinone}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS3_HOME="$INSTALL_DIR/ns-$NS3_VERSION"

echo "==> [1/5] Installing system packages (sudo may ask for your password)"
sudo apt-get update
sudo apt-get install -y g++ cmake ninja-build git python3 python3-pip python3-venv pkg-config \
    libzmq5 libzmq3-dev libprotobuf-dev protobuf-compiler ca-certificates curl tar bzip2

echo "==> [2/5] Getting ns-$NS3_VERSION in $NS3_HOME"
mkdir -p "$INSTALL_DIR"
if [ ! -f "$NS3_HOME/ns3" ]; then
    git clone --depth 1 --branch "ns-$NS3_VERSION" \
        https://gitlab.com/nsnam/ns-3-dev.git "$NS3_HOME"
fi

echo "==> [3/5] Adding the ns3-gym (opengym) module"
if [ ! -d "$NS3_HOME/contrib/opengym" ]; then
    git clone --depth 1 --branch app-ns-3.36+ \
        https://github.com/tkn-tub/ns3-gym.git "$NS3_HOME/contrib/opengym"
fi

echo "==> [4/5] Copying the DRL-ARCO scenario into ns-3"
bash "$REPO_DIR/scripts/sync_ns3.sh" "$NS3_HOME"

echo "==> [5/5] Configuring and building (first build takes 10-40 minutes)"
cd "$NS3_HOME"
./ns3 configure --build-profile=optimized --disable-tests --disable-examples \
    --enable-modules=core,network,internet,point-to-point,applications,flow-monitor,traffic-control,opengym
./ns3 build drl-arco

cat <<EOF

ns-3 is ready. Add this line to ~/.bashrc so Python can find it:

    export NS3_HOME="$NS3_HOME"

Then check the installation with:

    bash scripts/check_ns3.sh
EOF
