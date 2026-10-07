"""Product-layer UTC epoch-millisecond clock."""

import time


def utc_epoch_milliseconds() -> int:
    """Return the current UTC Unix epoch timestamp in milliseconds."""
    return time.time_ns() // 1_000_000
