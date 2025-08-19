"""Network request monitoring functionality for comprehensive monitoring."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from ..core.connector import ChromeConnector
from ..utils.event_id import make_event_id, make_network_event_id

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
        self.hostname = None
        
        # Stack enhancement attributes (new)
        self.debugger_enabled = False
        self.stack_candidates = {}  # LRU cache: requestId -> {snapshot, cached_at, url, resource_type}
        self.max_candidates = 300  # LRU limit
        self.api_count = {}  # (origin, path) -> count for high frequency detection
        self.resource_count = {}  # (origin, path) -> count for repeated resource detection
        
        # Debug statistics (new)
        self._recent_triggers = []  # Recent trigger records for debugging
        self._debug_stats = {
            "total_candidates_cached": 0,
            "total_stacks_collected": 0,
            "debugger_enable_attempts": 0,
            "debugger_enable_failures": 0
        }
        
        # WebSocket monitoring attributes
        self.websocket_connections = {}  # requestId -> {url, created_at}
        self.websocket_frame_stats = {}  # (hostname, path) -> frame_count_per_second
        
    def set_hostname(self, hostname: str):
        """Set hostname for data grouping."""
        self.hostname = hostname
        
    async def start_monitoring(self) -> None:
        """Start Network event listening."""
        self.connector.on_event("Network.requestWillBeSent", self._on_request_start)
        self.connector.on_event("Network.responseReceived", self._on_response_received)
        self.connector.on_event("Network.loadingFinished", self._on_request_finished)
        self.connector.on_event("Network.loadingFailed", self._on_request_failed)
        
        # WebSocket lifecycle events
        self.connector.on_event("Network.webSocketCreated", self._on_websocket_created)
        self.connector.on_event("Network.webSocketFrameSent", self._on_websocket_frame_sent)
        self.connector.on_event("Network.webSocketFrameReceived", self._on_websocket_frame_received)
        self.connector.on_event("Network.webSocketFrameError", self._on_websocket_frame_error)
        self.connector.on_event("Network.webSocketClosed", self._on_websocket_closed)
        
        # Enable Debugger for enhanced stack collection
        await self._enable_debugger_globally()
    
    async def stop_monitoring(self) -> None:
        """Stop Network event listening with paired off_event."""
        self.connector.off_event("Network.requestWillBeSent", self._on_request_start)
        self.connector.off_event("Network.responseReceived", self._on_response_received)
        self.connector.off_event("Network.loadingFinished", self._on_request_finished)
        self.connector.off_event("Network.loadingFailed", self._on_request_failed)
        
        # WebSocket event cleanup
        self.connector.off_event("Network.webSocketCreated", self._on_websocket_created)
        self.connector.off_event("Network.webSocketFrameSent", self._on_websocket_frame_sent)
        self.connector.off_event("Network.webSocketFrameReceived", self._on_websocket_frame_received)
        self.connector.off_event("Network.webSocketFrameError", self._on_websocket_frame_error)
        self.connector.off_event("Network.webSocketClosed", self._on_websocket_closed)
    
    async def _on_request_start(self, params: dict) -> None:
        """Request start - pure queue path: filter→limit→construct metadata→enqueue."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
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
        
        # NEW: Judge and cache candidate initiator (XHR/Fetch always cached; Script only when JS stack exists)
        candidate_reason = self._should_cache_initiator(params)
        if candidate_reason:
            self._cache_trimmed_initiator(
                request_id=request_id,
                raw_initiator=params["initiator"],
                url=params.get("request", {}).get("url", ""),
                resource_type=params.get("type", ""),
                initial_reason=candidate_reason  # Save initial trigger reason
            )
            
        # NEW: Update counts (for subsequent trigger determination)
        self._update_request_counts(params)
        
        # Cache request data (existing logic unchanged)
        self.pending_requests[request_id] = request_data
        # Add event_id using enhanced network event ID generator
        try:
            request_data["event_id"] = make_network_event_id(
                "network_request_start",
                self.hostname or "",
                request_data.get("timestamp", ""),
                request_id,
                method=request_data.get("method", ""),
                url=request_data.get("url", "")
            )
        except Exception:
            pass
        
        # Single exit: enqueue for processing
        try:
            self.event_queue.put_nowait(("network_request_start", request_data))
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
        
        # NEW: Final confirmation and attach detailedStack
        candidate = self.stack_candidates.get(request_id)
        final_reason = self._confirm_detailed_stack_needed(url=request_data.get("url", ""), params=params, candidate=candidate)
        if final_reason:
            if candidate:
                detailed_stack = self._format_detailed_stack(candidate["snapshot"])
                request_data["detailedStack"] = {
                    "enabled": True,
                    "reason": final_reason,
                    "collectionTime": datetime.now(timezone.utc).isoformat(),
                    **detailed_stack
                }
                # Record successful trigger event
                self._record_trigger_event(final_reason, request_id, request_data.get("url", ""), True)
            else:
                # No candidate: also output reason, avoid gaps
                request_data["detailedStack"] = {
                    "enabled": False,
                    "reason": final_reason,
                    "collectionTime": datetime.now(timezone.utc).isoformat()
                }
                # Record failed trigger event (has reason but no candidate)
                self._record_trigger_event(final_reason, request_id, request_data.get("url", ""), False)
        
        # Clean up candidate cache
        self.stack_candidates.pop(request_id, None)
        
        # Single exit: enqueue for processing (existing logic unchanged)
        # Add event_id with enhanced uniqueness for complete events
        try:
            request_data["event_id"] = make_network_event_id(
                "network_request_complete",
                self.hostname or "",
                request_data.get("timestamp", ""),
                request_id,
                status=request_data.get("status", 0),
                responseSize=request_data.get("responseSize", 0),
                encodedDataLength=encoded_length,
                url=request_data.get("url", "")
            )
        except Exception:
            pass
        try:
            self.event_queue.put_nowait(("network_request_complete", request_data))
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
        # Add event_id with error details for uniqueness
        try:
            request_data["event_id"] = make_network_event_id(
                "network_request_failed",
                self.hostname or "",
                request_data.get("timestamp", ""),
                request_id,
                url=request_data.get("url", ""),
                errorText=request_data.get("errorText", "")
            )
        except Exception:
            pass
        
        # Single exit: enqueue for processing
        try:
            self.event_queue.put_nowait(("network_request_failed", request_data))
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
    
    # Stack Enhancement Methods (new)
    
    async def _enable_debugger_globally(self):
        """Enable Debugger domain globally for detailed stack collection."""
        self._debug_stats["debugger_enable_attempts"] += 1
        try:
            await self.connector.call("Debugger.enable", session_id=self.session_id)
            await self.connector.call("Debugger.setAsyncCallStackDepth", 
                                    {"maxDepth": 15}, session_id=self.session_id)
            self.debugger_enabled = True
            logger.info(f"Debugger enabled for detailed stack collection (session: {self.session_id})")
        except Exception as e:
            self._debug_stats["debugger_enable_failures"] += 1
            logger.debug(f"Failed to enable debugger for session {self.session_id}: {e}")
            # Graceful degradation, does not affect basic network monitoring
    
    def _should_cache_initiator(self, params: dict) -> Optional[str]:
        """Determine if initiator should be cached (requestWillBeSent phase)."""
        resource_type = params.get("type", "")
        
        # Primary target: XHR/Fetch (data requests)
        if resource_type in ["XHR", "Fetch"]:
            request = params.get("request", {})
            # Large upload detection
            if len(request.get("postData", "")) > 102400:  # 100KB
                return "large_upload"
            # Cache all XHR/Fetch as candidates (main value scenario)
            return "xhr_fetch_candidate"
        
        # Supplementary target: Script with JS stack (dynamic loading scenarios)
        elif resource_type == "Script" and params.get("initiator", {}).get("stack"):
            return "script_with_stack"
        
        return None  # Other types not cached
    
    def _confirm_detailed_stack_needed(self, url: str, params: dict, candidate: Optional[dict] = None) -> Optional[str]:
        """Final confirmation if detailed stack is needed (loadingFinished phase)."""
        # Priority 1: Large download confirmation (higher priority than upload)
        encoded_length = params.get("encodedDataLength", 0)
        if encoded_length > 102400:  # 100KB
            return "large_download"
        
        # Priority 2: Check initial trigger reason from candidate (for large_upload only cases)
        if candidate and candidate.get("initial_reason") == "large_upload":
            return "large_upload"
        
        # Priority 3: Count-based trigger confirmation (ADJUSTED THRESHOLDS)
        origin, path = self._parse_origin_path(url)
        
        # High frequency API (>=10 times, lowered from 50)
        api_count = self.api_count.get((origin, path), 0)
        if api_count >= 10:  # Lowered threshold for earlier detection
            return f"high_frequency_api_{api_count}"
            
        # Repeated resource (>=3 times and >10KB single, lowered from 5)
        resource_count = self.resource_count.get((origin, path), 0)
        if resource_count >= 3 and encoded_length > 10240:  # 10KB
            return f"repeated_resource_{resource_count}"
        
        return None
    
    def _parse_origin_path(self, url: str) -> tuple:
        """Parse URL to (origin, path), removing query interference."""
        try:
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            path = parsed.path or "/"
            return (origin, path)
        except:
            return (url, "/")  # Fallback
    
    def _cache_trimmed_initiator(self, request_id: str, raw_initiator: dict, url: str, resource_type: str, initial_reason: str):
        """Cache trimmed initiator snapshot."""
        # LRU eviction strategy
        if len(self.stack_candidates) >= self.max_candidates:
            # Evict oldest based on cached_at, avoiding dependency on pending_requests
            oldest_id = min(self.stack_candidates, key=lambda k: self.stack_candidates[k]["cached_at"])
            self.stack_candidates.pop(oldest_id, None)
        
        # Immediate trimming: frames≤30, asyncFrames≤15, string truncation
        trimmed = self._trim_initiator_snapshot(raw_initiator)
        self.stack_candidates[request_id] = {
            "snapshot": trimmed,
            "cached_at": datetime.now(timezone.utc).timestamp(),
            "url": url,
            "resource_type": resource_type,
            "initial_reason": initial_reason  # Save the initial trigger reason
        }
        
        # Update debug statistics
        self._debug_stats["total_candidates_cached"] += 1
    
    def _trim_initiator_snapshot(self, raw_initiator: dict) -> dict:
        """Trim initiator snapshot to control memory (adjusted precision)."""
        if not raw_initiator.get("stack"):
            return {"type": raw_initiator.get("type", "unknown")}
            
        trimmed = {"type": raw_initiator.get("type", "unknown")}
        stack = raw_initiator["stack"]
        
        # Adjustment: Increase main stack frames limit to 30, retain more debug info
        if stack.get("callFrames"):
            def trim_frames(frames, limit):
                out = []
                for frame in frames[:limit]:
                    out.append({
                        "functionName": str(frame.get("functionName", ""))[:150],  # Increase to 150 chars
                        "url": str(frame.get("url", ""))[:300],  # Increase to 300 chars
                        "lineNumber": int(frame.get("lineNumber", 0)),
                        "columnNumber": int(frame.get("columnNumber", 0)),
                        "scriptId": str(frame.get("scriptId", ""))[:50]
                    })
                return out

            trimmed_stack = {"callFrames": trim_frames(stack.get("callFrames", []), 30)}  # Increase to 30 frames

            # Adjustment: Async parent stack chain increase to 15 layers, retain more async context
            parent_src = stack
            parent_dst = trimmed_stack
            depth = 0
            while parent_src.get("parent") and depth < 15:  # Increase to 15 layers
                parent_src = parent_src["parent"]
                node = {"callFrames": trim_frames(parent_src.get("callFrames", []), 30)}  # Each layer also 30 frames
                parent_dst["parent"] = node
                parent_dst = node
                depth += 1

            trimmed["stack"] = trimmed_stack
        
        return trimmed
    
    def _format_detailed_stack(self, trimmed_initiator: dict) -> dict:
        """Parse cached call stack snapshot (adjusted truncation judgment)."""
        frames = []
        async_frames = []
        
        stack = trimmed_initiator.get("stack", {})
        
        # Parse main call stack
        if stack.get("callFrames"):
            frames = stack["callFrames"]  # Already trimmed during caching
            
        # Parse async call stack (parent attributes)
        current_stack = stack
        while current_stack.get("parent"):
            current_stack = current_stack["parent"]
            if current_stack.get("callFrames"):
                async_frames.extend(current_stack["callFrames"])
        
        return {
            "frames": frames,
            "asyncFrames": async_frames[:15],  # Adjust secondary protection limit
            "truncated": len(frames) >= 30 or len(async_frames) >= 15  # Adjust truncation judgment
        }
    
    def _update_request_counts(self, params: dict):
        """Update API and resource counts."""
        url = params.get("request", {}).get("url", "")
        origin, path = self._parse_origin_path(url)
        
        resource_type = params.get("type", "")
        if resource_type in ["XHR", "Fetch"]:
            self.api_count[(origin, path)] = self.api_count.get((origin, path), 0) + 1
        elif resource_type == "Script" and any(ext in path for ext in [".js", ".css", ".json"]):
            self.resource_count[(origin, path)] = self.resource_count.get((origin, path), 0) + 1
    
    def _record_trigger_event(self, reason: str, request_id: str, url: str, enabled: bool):
        """Record trigger event for debugging."""
        trigger_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "requestId": request_id,
            "url": url[:100],
            "enabled": enabled
        }
        self._recent_triggers.append(trigger_record)
        
        # Keep recent 50 records
        if len(self._recent_triggers) > 50:
            self._recent_triggers.pop(0)
            
        # Update lifecycle statistics
        if enabled:
            self._debug_stats["total_stacks_collected"] += 1
    
    def get_debug_stats(self) -> dict:
        """Get debugging statistics."""
        return {
            "candidates_cached": len(self.stack_candidates),
            "api_count_entries": len(self.api_count),
            "resource_count_entries": len(self.resource_count),
            "debugger_enabled": self.debugger_enabled,
            "recent_triggers": self._recent_triggers[-10:],  # Recent 10 trigger records
            "lifetime_stats": self._debug_stats.copy()
        }
    
    # WebSocket Event Handlers
    
    async def _on_websocket_created(self, params: dict) -> None:
        """WebSocket connection created - store URL mapping."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        request_id = params["requestId"]
        url = params["url"]
        
        # Store connection info for later frame events
        self.websocket_connections[request_id] = {
            "url": url,
            "created_at": time.time()
        }
        
        # Create connection created event
        connection_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "websocket_created",
            "requestId": request_id,
            "url": url[:500],  # Truncate URL like HTTP requests
            "hostname": self.hostname,
            "sessionId": self.session_id
        }
        
        # Generate event_id
        try:
            connection_data["event_id"] = make_event_id(
                "websocket_created",
                self.hostname or "",
                connection_data["timestamp"],
                request_id,
                url[:100]  # Include URL hash for uniqueness
            )
        except Exception:
            pass
        
        # Enqueue event
        try:
            self.event_queue.put_nowait(("websocket_created", connection_data))
        except asyncio.QueueFull:
            logger.warning("Network event queue full, dropping websocket_created")
    
    async def _on_websocket_frame_sent(self, params: dict) -> None:
        """WebSocket frame sent event."""
        await self._process_websocket_frame(params, "websocket_frame_sent")
    
    async def _on_websocket_frame_received(self, params: dict) -> None:
        """WebSocket frame received event."""
        await self._process_websocket_frame(params, "websocket_frame_received")
    
    async def _process_websocket_frame(self, params: dict, event_type: str) -> None:
        """Process WebSocket frame event (sent or received)."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        request_id = params["requestId"]
        
        # Get URL from stored connection info
        connection_info = self.websocket_connections.get(request_id)
        if not connection_info:
            # Connection not tracked, create minimal data
            url = "unknown"
            connection_age = 0
        else:
            url = connection_info["url"]
            connection_age = time.time() - connection_info["created_at"]
        
        # Extract frame data
        response = params.get("response", {})
        opcode = response.get("opcode", 0)
        payload_data = response.get("payloadData", "")
        
        # Build frame data
        frame_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "requestId": request_id,
            "url": url[:500],
            "opcode": opcode,
            "payloadLength": len(payload_data),
            "hostname": self.hostname,
            "sessionId": self.session_id
        }
        
        # Handle payload based on opcode
        if opcode == 1:  # Text frame
            frame_data["payloadText"] = payload_data[:1024]  # Truncate to 1024 chars
            if len(payload_data) > 1024:
                frame_data["payloadText"] += "...[truncated]"
        elif opcode == 2:  # Binary frame
            # For binary frames, only record length and type
            frame_data["payloadType"] = "binary"
            # Don't store payload content for binary frames
        # For control frames (ping/pong/close), opcode is recorded but no payload
        
        # Add frame statistics
        frame_data["frameStats"] = self._get_frame_stats(url, connection_age)
        
        # Generate event_id
        try:
            frame_data["event_id"] = make_event_id(
                event_type,
                self.hostname or "",
                frame_data["timestamp"],
                request_id,
                opcode,
                len(payload_data)
            )
        except Exception:
            pass
        
        # Enqueue event
        try:
            self.event_queue.put_nowait((event_type, frame_data))
        except asyncio.QueueFull:
            logger.warning(f"Network event queue full, dropping {event_type}")
    
    async def _on_websocket_frame_error(self, params: dict) -> None:
        """WebSocket frame error event."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        request_id = params["requestId"]
        error_message = params.get("errorMessage", "Unknown WebSocket error")
        
        # Get URL from stored connection info
        connection_info = self.websocket_connections.get(request_id)
        url = connection_info["url"] if connection_info else "unknown"
        
        error_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "websocket_frame_error",
            "requestId": request_id,
            "url": url[:500],
            "errorMessage": error_message[:200],  # Truncate error message
            "hostname": self.hostname,
            "sessionId": self.session_id
        }
        
        # Generate event_id
        try:
            error_data["event_id"] = make_event_id(
                "websocket_frame_error",
                self.hostname or "",
                error_data["timestamp"],
                request_id,
                error_message[:50]
            )
        except Exception:
            pass
        
        # Enqueue event
        try:
            self.event_queue.put_nowait(("websocket_frame_error", error_data))
        except asyncio.QueueFull:
            logger.warning("Network event queue full, dropping websocket_frame_error")
    
    async def _on_websocket_closed(self, params: dict) -> None:
        """WebSocket connection closed event."""
        # sessionId filtering
        if params.get("sessionId") != self.session_id:
            return
            
        request_id = params["requestId"]
        
        # Get URL from stored connection info
        connection_info = self.websocket_connections.get(request_id)
        url = connection_info["url"] if connection_info else "unknown"
        
        closed_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "websocket_closed",
            "requestId": request_id,
            "url": url[:500],
            "hostname": self.hostname,
            "sessionId": self.session_id
        }
        
        # Generate event_id
        try:
            closed_data["event_id"] = make_event_id(
                "websocket_closed",
                self.hostname or "",
                closed_data["timestamp"],
                request_id
            )
        except Exception:
            pass
        
        # Clean up connection tracking
        self.websocket_connections.pop(request_id, None)
        
        # Enqueue event
        try:
            self.event_queue.put_nowait(("websocket_closed", closed_data))
        except asyncio.QueueFull:
            logger.warning("Network event queue full, dropping websocket_closed")
    
    def _get_frame_stats(self, url: str, connection_age: float) -> dict:
        """Get frame statistics for aggregation analysis."""
        try:
            parsed = urlparse(url)
            hostname = parsed.netloc or "unknown"
            path = parsed.path or "/"
            
            # Update frame count for current second
            current_second = int(time.time())
            stats_key = (hostname, path, current_second)
            
            if stats_key not in self.websocket_frame_stats:
                self.websocket_frame_stats[stats_key] = 0
            self.websocket_frame_stats[stats_key] += 1
            
            # Clean up old statistics (keep last 60 seconds)
            old_keys = [k for k in self.websocket_frame_stats.keys() if k[2] < current_second - 60]
            for old_key in old_keys:
                del self.websocket_frame_stats[old_key]
            
            return {
                "framesThisSecond": self.websocket_frame_stats[stats_key],
                "connectionAge": round(connection_age, 2)
            }
        except Exception as e:
            logger.debug(f"Error calculating frame stats: {e}")
            return {"framesThisSecond": 0, "connectionAge": 0}
