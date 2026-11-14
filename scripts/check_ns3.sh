#!/usr/bin/env bash
# Confirm that ns-3, the scenario and the Python bridge work together.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${NS3_HOME:?Set NS3_HOME first (see docs/NS3_SETUP.md)}"

if [ ! -f drl_arco/envs/proto/messages_pb2.py ]; then
    python scripts/gen_proto.py
fi
python scripts/check_ns3.py
