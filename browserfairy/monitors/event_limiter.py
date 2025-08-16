"""Event frequency limiter for comprehensive monitoring."""

import time
import logging

logger = logging.getLogger(__name__)


class EventLimiter:
    """Event frequency limiter with sliding window and drop counting."""
    
    def __init__(self):
        self.console_count = 0
        self.network_count = 0
        self.last_reset = time.time()
        self.max_console_per_second = 10  # Console event limit
        self.max_network_per_second = 50  # Network event limit
        
        # Drop counting for troubleshooting
        self.console_dropped_count = 0
        self.network_dropped_count = 0
        self.last_dropped_summary = {}
        
    def should_process_console(self) -> bool:
        """Check if console event should be processed."""
        self._reset_counters()
        if self.console_count >= self.max_console_per_second:
            self.console_dropped_count += 1
            self._update_dropped_summary("console")
            return False
        self.console_count += 1
        return True
        
    def should_process_network(self) -> bool:
        """Check if network event should be processed."""
        self._reset_counters()
        if self.network_count >= self.max_network_per_second:
            self.network_dropped_count += 1
            self._update_dropped_summary("network")
            return False
        self.network_count += 1
        return True
        
    def _reset_counters(self):
        """Reset counters every second (sliding window)."""
        now = time.time()
        if now - self.last_reset >= 1.0:
            # Log drop statistics before reset
            if self.console_dropped_count > 0 or self.network_dropped_count > 0:
                logger.debug(f"Event limiter stats: console_dropped={self.console_dropped_count}, "
                           f"network_dropped={self.network_dropped_count}")
            
            self.console_count = 0
            self.network_count = 0
            self.console_dropped_count = 0
            self.network_dropped_count = 0
            self.last_reset = now
    
    def _update_dropped_summary(self, event_type: str):
        """Update dropped event summary for troubleshooting."""
        now = time.time()
        if now - self.last_dropped_summary.get(event_type, 0) > 5.0:  # 5 second interval
            logger.warning(f"Dropping {event_type} events due to rate limiting")
            self.last_dropped_summary[event_type] = now