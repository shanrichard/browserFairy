"""Console monitoring functionality for comprehensive monitoring."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..core.connector import ChromeConnector
from ..utils.event_id import make_event_id

logger = logging.getLogger(__name__)


class ConsoleMonitor:
    """Console log monitor - per-session filtering with a queue."""
    
    def __init__(self, connector: ChromeConnector, session_id: str,
                 event_queue: asyncio.Queue, status_callback: Optional[Callable] = None,
                 enable_source_map: bool = False):
        self.connector = connector
        # In flattened mode, CDP events include a top-level sessionId injected by connector
        # Keep a strict per-session filter to avoid cross-tab duplication
        self.session_id = session_id
        self.event_queue = event_queue
        self.status_callback = status_callback
        self.hostname = None
        
        # Source Map support (v1: disabled by default)
        self.enable_source_map = enable_source_map
        self.source_map_resolver = None
        
    def set_hostname(self, hostname: str):
        """Set hostname for data grouping."""
        self.hostname = hostname
        
    async def start_monitoring(self) -> None:
        """Start Console event listening with optional source map support."""
        logger.debug(f"ConsoleMonitor.start_monitoring: registering handlers for session {self.session_id}")
        self.connector.on_event("Runtime.consoleAPICalled", self._on_console_message)
        self.connector.on_event("Runtime.exceptionThrown", self._on_exception_thrown)
        logger.debug(f"ConsoleMonitor handlers registered")
        
        # Initialize Source Map resolver if enabled
        if self.enable_source_map:
            try:
                from ..analysis.source_map import SourceMapResolver
                self.source_map_resolver = SourceMapResolver(self.connector)
                await self.source_map_resolver.initialize(self.session_id)
                logger.debug(f"Source map resolver initialized for session {self.session_id}")
            except Exception as e:
                logger.debug(f"Source map resolver initialization failed: {e}")
    
    async def stop_monitoring(self) -> None:
        """Stop Console event listening with paired off_event."""
        self.connector.off_event("Runtime.consoleAPICalled", self._on_console_message)
        self.connector.off_event("Runtime.exceptionThrown", self._on_exception_thrown)
        
        # Clean up Source Map resolver if enabled
        if self.source_map_resolver:
            await self.source_map_resolver.cleanup()
            self.source_map_resolver = None
        
    async def _on_console_message(self, params: dict) -> None:
        """Handle console message - pure queue path: filter→limit→construct→enqueue."""
        # Strictly filter by session to avoid cross-tab duplication
        if params.get("sessionId") != self.session_id:
            return
        
        # Construct lightweight event data
        console_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "console",
            "level": params["type"],
            "message": self._extract_and_truncate_message(params.get("args", [])),
            "source": self._extract_source(params),
            "hostname": self.hostname
        }
        # Add event_id
        console_data["event_id"] = make_event_id(
            "console",
            self.hostname or "",
            console_data["timestamp"],
            console_data.get("level", ""),
            console_data.get("message", ""),
            (console_data.get("source", {}) or {}).get("url", ""),
            (console_data.get("source", {}) or {}).get("line", 0)
        )
        
        # Single exit: enqueue for processing (drop when full)
        try:
            self.event_queue.put_nowait(("console", console_data))
        except asyncio.QueueFull:
            logger.warning("Console event queue full, dropping event")
            
        # Status callback (important events only, non-blocking)
        if params["type"] in ["error", "warn"] and self.status_callback:
            try:
                self.status_callback("console_error", {
                    "level": params["type"],
                    "message": console_data["message"][:50],
                    "source": console_data["source"].get("function", "unknown")
                })
            except Exception as e:
                logger.warning(f"Error in console status callback: {e}")
    
    async def _on_exception_thrown(self, params: dict) -> None:
        """Handle JavaScript exception - pure queue path: filter→construct→enqueue."""
        # Strictly filter by session to avoid cross-tab duplication
        if params.get("sessionId") != self.session_id:
            return
            
        exception = params["exceptionDetails"]
        exception_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "exception",
            "message": exception["text"][:500],
            "source": {
                "url": exception.get("url", "")[:200],
                "line": exception.get("lineNumber", 0),
                "column": exception.get("columnNumber", 0)
            },
            "stackTrace": self._format_stack_trace(exception.get("stackTrace", {})),
            "hostname": self.hostname
        }
        
        # Apply Source Map resolution if enabled
        if self.source_map_resolver and exception_data.get("stackTrace"):
            try:
                # Add short timeout to avoid blocking main monitoring flow
                exception_data["stackTrace"] = await asyncio.wait_for(
                    self.source_map_resolver.resolve_stack_trace(
                        exception_data["stackTrace"]
                    ),
                    timeout=0.2
                )
            except asyncio.TimeoutError:
                logger.debug("Source map resolution timed out; keeping original stack")
            except Exception as e:
                logger.debug(f"Source map resolution failed: {e}")
                # Failed: keep original stack trace
        
        # Add event_id
        exception_data["event_id"] = make_event_id(
            "exception",
            self.hostname or "",
            exception_data["timestamp"],
            exception_data.get("message", ""),
            exception_data.get("source", {}).get("url", ""),
            exception_data.get("source", {}).get("line", 0),
            exception_data.get("source", {}).get("column", 0)
        )
        
        # Single exit: enqueue for processing
        try:
            self.event_queue.put_nowait(("exception", exception_data))
        except asyncio.QueueFull:
            logger.warning("Exception event queue full, dropping event")
        
        # Status callback notification
        if self.status_callback:
            try:
                self.status_callback("console_error", {
                    "level": "exception",
                    "message": exception_data["message"][:50],
                    "source": exception_data["source"]["url"][:30]
                })
            except Exception as e:
                logger.warning(f"Error in exception status callback: {e}")
    
    def _extract_and_truncate_message(self, args: list, max_length: int = 500) -> str:
        """Unified method: extract and limit message length to ≤500 characters."""
        messages = []
        for arg in args:
            if arg.get("type") == "string":
                messages.append(arg.get("value", ""))
            elif arg.get("type") == "object":
                messages.append(str(arg.get("description", arg.get("value", ""))))
            else:
                messages.append(str(arg.get("value", "")))
        
        full_message = " ".join(messages)
        if len(full_message) <= max_length:
            return full_message
        return full_message[:max_length] + "...[truncated]"
    
    def _extract_source(self, params: dict) -> dict:
        """Extract call source information."""
        stack = params.get("stackTrace", {})
        if stack and stack.get("callFrames"):
            frame = stack["callFrames"][0]
            return {
                "url": frame.get("url", "")[:200],
                "line": frame.get("lineNumber", 0),
                "function": frame.get("functionName", "anonymous")[:100]
            }
        return {"url": "", "line": 0, "function": "unknown"}
    
    def _format_stack_trace(self, stack: dict) -> list:
        """Format stack trace information - preserve backward compatibility, add new fields."""
        if not stack or not stack.get("callFrames"):
            return []
        
        return [
            {
                # Keep original field names for backward compatibility
                "function": frame.get("functionName", "anonymous")[:100],
                "url": frame.get("url", "")[:200],
                "line": frame.get("lineNumber", 0),
                "column": frame.get("columnNumber", 0),
                # Add new fields for Source Map resolution
                "scriptId": frame.get("scriptId"),  # Required for Source Map lookup
                "lineNumber": frame.get("lineNumber", 0),  # CDP original field
                "columnNumber": frame.get("columnNumber", 0)  # CDP original field
            }
            for frame in stack["callFrames"][:5]
        ]
