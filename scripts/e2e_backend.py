#!/usr/bin/env python3
"""Run one E2E Uvicorn worker with a graceful stdin shutdown contract."""

from __future__ import annotations

import argparse
from threading import Thread
import sys

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    config = uvicorn.Config(
        "strata_backend.main:app", host="127.0.0.1", port=args.port,
        workers=1, log_level="warning", access_log=False,
    )
    server = uvicorn.Server(config)
    worker = Thread(target=server.run, name="strata-e2e-uvicorn", daemon=False)
    worker.start()
    try:
        for line in sys.stdin:
            if line.strip() == "stop":
                break
    finally:
        server.should_exit = True
        worker.join(timeout=20)
    return 0 if not worker.is_alive() else 1


if __name__ == "__main__":
    raise SystemExit(main())
