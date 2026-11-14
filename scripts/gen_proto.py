#!/usr/bin/env python3
"""Generate messages_pb2.py so it always matches the installed protobuf package."""

from __future__ import annotations

import sys
from pathlib import Path

import grpc_tools
from grpc_tools import protoc

PROTO_DIR = Path(__file__).resolve().parent.parent / "drl_arco" / "envs" / "proto"
WELL_KNOWN = Path(grpc_tools.__file__).parent / "_proto"

code = protoc.main(["protoc", f"-I{PROTO_DIR}", f"-I{WELL_KNOWN}", f"--python_out={PROTO_DIR}",
                    str(PROTO_DIR / "messages.proto")])
if code != 0:
    sys.exit(code)
print(f"generated {PROTO_DIR / 'messages_pb2.py'}")
