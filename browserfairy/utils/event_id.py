"""Lightweight event_id generator for deduplication.

Design goals:
- Very low overhead (tiny input, fast hash, no extra deps)
- Stable across runs given same key fields
- Short hex string for readability
- Enhanced uniqueness for network events
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional


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


def make_network_event_id(
    kind: str, 
    hostname: str, 
    timestamp: str, 
    request_id: str,
    sequence: Optional[int] = None,
    **extra_fields: Any
) -> str:
    """Enhanced event_id for network events to avoid duplicates.
    
    For network_request_complete events that might be duplicated by CDP,
    we add additional uniqueness factors:
    - sequence: An optional sequence number for ordering multiple events
    - extra_fields: Additional fields like responseSize, encodedDataLength
    
    This ensures that even if CDP sends duplicate events, they get different IDs
    if they have any different properties.
    """
    parts = [kind, hostname, timestamp, request_id]
    
    # Add sequence number if provided (for disambiguating true duplicates)
    if sequence is not None:
        parts.append(f"seq:{sequence}")
    
    # For start events, include method and URL
    if kind == "network_request_start" and extra_fields:
        if "method" in extra_fields:
            parts.append(f"method:{extra_fields['method']}")
        if "url" in extra_fields:
            # Include a hash of URL to avoid huge IDs but maintain uniqueness
            url_hash = hashlib.blake2s(extra_fields['url'].encode(), digest_size=8).hexdigest()[:8]
            parts.append(f"url:{url_hash}")
    
    # For complete events, add more unique fields to detect variations
    elif kind == "network_request_complete" and extra_fields:
        # Include response size and encoded size as they might differ
        if "responseSize" in extra_fields:
            parts.append(f"size:{extra_fields['responseSize']}")
        if "encodedDataLength" in extra_fields:
            parts.append(f"encoded:{extra_fields['encodedDataLength']}")
        if "status" in extra_fields:
            parts.append(f"status:{extra_fields['status']}")
    
    # For failed events, include error details
    elif kind == "network_request_failed" and extra_fields:
        if "errorText" in extra_fields:
            parts.append(f"error:{extra_fields['errorText']}")
    
    base = "|".join(_to_str(p) for p in parts)
    h = hashlib.blake2s(base.encode("utf-8"), digest_size=10)
    return h.hexdigest()

