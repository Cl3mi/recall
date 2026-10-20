"""Airlock window marker: while it exists, the guard denies every tool call."""

from __future__ import annotations

from datetime import datetime, timezone

from .config import load_config

USAGE = "usage: airlock open|close|status"


def is_open(cfg) -> bool:
    return cfg.airlock_marker.exists()


def main(argv: list, cfg=None) -> int:
    cfg = cfg or load_config(lenient=True)
    command = argv[0] if argv else ""
    if command == "open":
        cfg.airlock_marker.parent.mkdir(parents=True, exist_ok=True)
        # datetime.UTC needs 3.11; the hook must run on older system pythons
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017
        cfg.airlock_marker.write_text(f"opened {stamp}\n", encoding="utf-8")
        print("airlock window OPEN: all AI tool calls in this repo are denied until you close it")
        return 0
    if command == "close":
        cfg.airlock_marker.unlink(missing_ok=True)
        print("airlock window closed: AI tool calls are allowed again")
        return 0
    if command == "status":
        print("airlock window OPEN" if is_open(cfg) else "airlock window closed")
        return 0
    print(USAGE)
    return 2
