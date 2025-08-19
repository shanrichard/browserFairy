"""Simple correlation engine for time window analysis."""

import time
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Callable

from ..utils.event_id import make_event_id

logger = logging.getLogger(__name__)


class SimpleCorrelationEngine:
    """Simplified correlation analysis engine - time window simple rule correlation."""
    
    def __init__(self, status_callback: Optional[Callable] = None):
        self.status_callback = status_callback
        self.recent_events = deque(maxlen=20)  # Limit buffer size
        self.correlation_window = 15.0  # ±15 seconds correlation window
        
    def add_event(self, event_data: dict) -> Optional[dict]:
        """Add event and check time window correlations."""
        current_time = time.time()
        
        # Check correlations in recent events
        correlations = []
        for recent_event in list(self.recent_events):
            time_diff = current_time - recent_event["event_time"]
            if time_diff <= self.correlation_window:
                correlation = self._check_simple_correlation(event_data, recent_event["data"])
                if correlation:
                    correlations.append(correlation)
        
        # Add new event to buffer
        self.recent_events.append({
            "data": event_data,
            "event_time": current_time
        })
        
        # If correlations found, generate report
        if correlations:
            timestamp = datetime.now(timezone.utc).isoformat()
            hostname = event_data.get("hostname", "unknown")
            correlation_report = {
                "timestamp": timestamp,
                "type": "correlation",
                "hostname": hostname,
                "primary_event": {
                    "type": event_data.get("type", "unknown"),
                    "timestamp": event_data.get("timestamp", "")
                },
                "correlations": correlations[:2],  # Limit count
                "severity": self._determine_severity(correlations),
                "evidence": "Time window correlation detected"
            }
            
            # Add event_id for deduplication
            try:
                # Use primary event type, timestamp, and correlation types for uniqueness
                correlation_types = "|".join(c.get("type", "") for c in correlations[:2])
                correlation_report["event_id"] = make_event_id(
                    "correlation",
                    hostname,
                    timestamp,
                    event_data.get("type", "unknown"),
                    correlation_types,
                    len(correlations)
                )
            except Exception:
                pass  # Continue without event_id if generation fails
            
            # Status callback
            if self.status_callback:
                try:
                    self.status_callback("correlation_found", {
                        "count": len(correlations),
                        "severity": correlation_report["severity"],
                        "types": [c.get("type", "") for c in correlations]
                    })
                except Exception as e:
                    logger.warning(f"Correlation status callback error: {e}")
            
            return correlation_report
        
        return None
    
    def _check_simple_correlation(self, event1: dict, event2: dict) -> Optional[dict]:
        """Check simple correlation rules between two events."""
        # Rule 1: Large network response → Memory collection
        if (event1.get("type") == "memory" and 
            event2.get("type") in ["network_request_complete"] and
            (event2.get("largeDataAlert") or event2.get("largeResponseAlert"))):
            
            size = 0
            if event2.get("largeDataAlert"):
                size = event2["largeDataAlert"].get("size", 0)
            elif event2.get("largeResponseAlert"):
                size = event2["largeResponseAlert"].get("size", 0)
                
            return {
                "type": "large_network_to_memory",
                "network_size_mb": round(size / (1024 * 1024), 1) if size > 0 else 0,
                "evidence": "Large network data followed by memory collection"
            }
        
        # Rule 2: Console error → Network failure
        if (event1.get("type") in ["console", "exception"] and 
            event1.get("level") in ["error", "exception"] and
            event2.get("type") in ["network_request_failed", "network_request_complete"] and 
            (event2.get("status", 0) >= 400 or event2.get("type") == "network_request_failed")):
            
            return {
                "type": "console_error_to_network_failure",
                "network_status": event2.get("status", 0),
                "error_message": event2.get("errorText", "")[:100],
                "evidence": "Console error correlates with network failure"
            }
        
        # Rule 3: Large network response → Console performance timing
        if (event1.get("type") == "console" and 
            event1.get("level") == "log" and
            "time" in event1.get("message", "").lower() and
            event2.get("type") == "network_request_complete" and
            event2.get("largeResponseAlert")):
            
            return {
                "type": "performance_timing_with_large_response",
                "response_size_mb": round(event2["largeResponseAlert"].get("size", 0) / (1024 * 1024), 1),
                "evidence": "Performance timing coincides with large response processing"
            }
        
        return None
    
    def _determine_severity(self, correlations: list) -> str:
        """Determine correlation severity."""
        if not correlations:
            return "info"
        
        # Check correlation types
        correlation_types = [c.get("type", "") for c in correlations]
        
        # Critical: Error-related correlations
        if "console_error_to_network_failure" in correlation_types:
            return "critical"
        
        # Warning: Large data processing related
        if any("large_network" in t for t in correlation_types):
            return "warning"
        
        # Info: Performance related
        if any("performance_timing" in t for t in correlation_types):
            return "info"
        
        return "info"