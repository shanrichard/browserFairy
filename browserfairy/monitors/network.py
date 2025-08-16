"""Network request monitoring functionality for comprehensive monitoring."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..core.connector import ChromeConnector
from .event_limiter import EventLimiter

logger = logging.getLogger(__name__)


class NetworkMonitor:
    """Network request monitor - pure queue mode, unified filter→limit→construct→enqueue."""
    
    def __init__(self, connector: ChromeConnector, session_id: str,
                 event_queue: asyncio.Queue, status_callback: Optional[Callable] = None):
        self.connector = connector
        self.session_id = session_id
        self.event_queue = event_queue
        self.status_callback = status_callback
        self.pending_requests: dict = {}  # requestId -> request metadata
        self.limiter = EventLimiter()
        self.hostname = None
        
    def set_hostname(self, hostname: str):
        """Set hostname for data grouping."""
        self.hostname = hostname
        
    async def start_monitoring(self) -> None:
        """Start Network event listening."""
        self.connector.on_event("Network.requestWillBeSent", self._on_request_start)
        self.connector.on_event("Network.responseReceived", self._on_response_received)
        self.connector.on_event("Network.loadingFinished", self._on_request_finished)
        self.connector.on_event("Network.loadingFailed", self._on_request_failed)
    
    async def stop_monitoring(self) -> None:
        """Stop Network event listening with paired off_event."""
        self.connector.off_event("Network.requestWillBeSent", self._on_request_start)
        self.connector.off_event("Network.responseReceived", self._on_response_received)
        self.connector.off_event("Network.loadingFinished", self._on_request_finished)
        self.connector.off_event("Network.loadingFailed", self._on_request_failed)
    
    async def _on_request_start(self, params: dict) -> None:
        """Request start - pure queue path: filter→limit→construct metadata→enqueue."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        # Event frequency control
        if not self.limiter.should_process_network():
            return
            
        request_id = params["requestId"]
        
        # Construct metadata (no full body capture)
        request_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "network_request_start", 
            "requestId": request_id,
            "url": params["request"]["url"][:500],
            "method": params["request"]["method"],
            "headers": self._truncate_headers(params["request"]["headers"]),
            "contentLength": len(params["request"].get("postData", "")),
            "initiator": self._format_initiator_simple(params["initiator"]),
            "startTime": params["timestamp"],  # CDP original monotonic time
            "hostname": self.hostname
        }
        
        # Large request detection
        content_length = request_data["contentLength"]
        if content_length > 1048576:  # 1MB
            request_data["largeDataAlert"] = {
                "size": content_length,
                "alert": "Large request body detected"
            }
            
            # Status callback (non-blocking)
            if self.status_callback:
                try:
                    self.status_callback("large_request", {
                        "url": request_data["url"][:50],
                        "size_mb": content_length / (1024 * 1024),
                        "method": request_data["method"]
                    })
                except Exception as e:
                    logger.warning(f"Error in large_request status callback: {e}")
        
        # Cache request data
        self.pending_requests[request_id] = request_data
        
        # Single exit: enqueue for processing
        try:
            self.event_queue.put_nowait(("network_start", request_data))
        except asyncio.QueueFull:
            logger.warning("Network event queue full, dropping request start")
    
    async def _on_response_received(self, params: dict) -> None:
        """Response received - update cached data (metadata only)."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        request_id = params["requestId"]
        if request_id in self.pending_requests:
            response_data = {
                "responseHeaders": self._truncate_headers(params["response"]["headers"]),
                "status": params["response"]["status"], 
                "mimeType": params["response"]["mimeType"][:100],
                "responseTime": params["timestamp"]
            }
            self.pending_requests[request_id].update(response_data)
    
    async def _on_request_finished(self, params: dict) -> None:
        """Request finished - pure queue path: filter→construct→enqueue."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        request_id = params["requestId"]
        if request_id not in self.pending_requests:
            return
            
        request_data = self.pending_requests.pop(request_id)
        
        # Large response detection
        response_size = params.get("encodedDataLength", 0)
        if response_size > 1048576:  # >1MB response
            request_data["largeResponseAlert"] = {
                "size": response_size,
                "alert": "Large response detected - potential 5.2MB JSON issue"
            }
            
            # Status callback (non-blocking)
            if self.status_callback:
                try:
                    self.status_callback("large_response", {
                        "url": request_data["url"][:50],
                        "size_mb": response_size / (1024 * 1024),
                        "status": request_data.get("status", 0)
                    })
                except Exception as e:
                    logger.warning(f"Error in large_response status callback: {e}")
        
        # Update completion info
        request_data.update({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "network_request_complete",
            "endTime": params["timestamp"],
            "duration": params["timestamp"] - request_data["startTime"],
            "encodedDataLength": response_size
        })
        
        # Single exit: enqueue for processing
        try:
            self.event_queue.put_nowait(("network_complete", request_data))
        except asyncio.QueueFull:
            logger.warning("Network event queue full, dropping request completion")
    
    async def _on_request_failed(self, params: dict) -> None:
        """Request failed - pure queue path: filter→construct→enqueue."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        request_id = params["requestId"]
        if request_id not in self.pending_requests:
            return
            
        request_data = self.pending_requests.pop(request_id)
        request_data.update({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "network_request_failed",
            "errorText": params.get("errorText", "Unknown error")[:200],
            "canceled": params.get("canceled", False),
            "hostname": self.hostname
        })
        
        # Single exit: enqueue for processing
        try:
            self.event_queue.put_nowait(("network_failed", request_data))
        except asyncio.QueueFull:
            logger.warning("Network event queue full, dropping request failure")
    
    def _truncate_headers(self, headers: dict, max_headers: int = 20, max_value_length: int = 256) -> dict:
        """Truncate HTTP headers: first 20 keys, each value ≤256 characters."""
        if not headers:
            return {}
            
        truncated = {}
        count = 0
        for key, value in headers.items():
            if count >= max_headers:
                truncated["...[truncated]"] = f"{len(headers) - max_headers} more headers"
                break
                
            truncated_key = key[:100] if isinstance(key, str) else str(key)[:100]
            truncated_value = value[:max_value_length] if isinstance(value, str) else str(value)[:max_value_length]
            
            if len(str(value)) > max_value_length:
                truncated_value += "...[truncated]"
                
            truncated[truncated_key] = truncated_value
            count += 1
            
        return truncated
    
    def _format_initiator_simple(self, initiator: dict) -> dict:
        """Format request initiator information (simplified version)."""
        result = {"type": initiator.get("type", "unknown")}
        
        if initiator.get("stack") and initiator["stack"].get("callFrames"):
            frame = initiator["stack"]["callFrames"][0]
            result["source"] = {
                "function": frame.get("functionName", "anonymous")[:100],
                "url": frame.get("url", "")[:200],
                "line": frame.get("lineNumber", 0)
            }
        
        return result