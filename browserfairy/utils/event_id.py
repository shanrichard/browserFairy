"""Lightweight event_id generator for deduplication.

Design goals:
- Very low overhead (tiny input, fast hash, no extra deps)
- Stable across runs given same key fields
- Short hex string for readability
"""

from __future__ import annotations

import hashlib
from typing import Any


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def make_event_id(kind: str, hostname: str, timestamp: str, *parts: Any) -> str:
    """Make a stable, short event_id.

    Uses blake2s with small digest (10 bytes => 20 hex chars).
    Input is a small, joined string to minimize overhead.
    """
    base = "|".join([_to_str(kind), _to_str(hostname), _to_str(timestamp)] + [_to_str(p) for p in parts])
    h = hashlib.blake2s(base.encode("utf-8"), digest_size=10)
    return h.hexdigest()

