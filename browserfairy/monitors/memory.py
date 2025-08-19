"""Memory monitoring functionality."""

import asyncio
import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..core.connector import ChromeConnector, ChromeConnectionError
from ..utils.event_id import make_event_id

# Conditional imports for comprehensive mode (avoid circular imports)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .console import ConsoleMonitor
    from .network import NetworkMonitor
    from ..analysis.correlation import SimpleCorrelationEngine

logger = logging.getLogger(__name__)

# Global semaphore to limit concurrent sampling across all collectors
SAMPLING_SEMAPHORE = asyncio.Semaphore(8)


class MemoryCollector:
    """Single tab memory metrics collector."""
    
    def __init__(self, connector: ChromeConnector, target_id: str, hostname: str,
                 data_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 enable_comprehensive: bool = False,
                 status_callback: Optional[Callable] = None):
        self.connector = connector
        self.target_id = target_id
        self.hostname = hostname
        self.session_id: Optional[str] = None
        self.collection_task: Optional[asyncio.Task] = None
        self.data_callback = data_callback
        self.running = False
        self._collecting = False  # Mutex flag to avoid re-entrance
        self.current_url = ""
        self.current_title = ""
        self.last_activity_time = datetime.now().timestamp()
        
        # New comprehensive monitoring parameters
        self.enable_comprehensive = enable_comprehensive
        self.status_callback = status_callback
        
        # New comprehensive components (initialized only when enabled)
        self.event_queue: Optional[asyncio.Queue] = None
        self.console_monitor: Optional['ConsoleMonitor'] = None
        self.network_monitor: Optional['NetworkMonitor'] = None
        self.domstorage_monitor: Optional[Any] = None
        self.gc_monitor: Optional[Any] = None  # Initialize gc_monitor attribute
        self.correlation_engine: Optional['SimpleCorrelationEngine'] = None
        self.event_consumer_task: Optional[asyncio.Task] = None
        self.consumer_running = False  # Independent lifecycle for event consumer
        
        # Event listener analysis related state
        self._event_listener_analysis_enabled = False
        self._last_listener_count = 0
        self._script_url_cache = {}  # scriptId -> url mapping
        self._detailed_analysis_task: Optional[asyncio.Task] = None  # Async analysis task tracking
        
    async def attach(self) -> None:
        """Establish Target-level session with retries and sane timeouts."""
        try:
            # Retry attach a few times for heavy pages
            last_err = None
            for attempt in range(3):
                try:
                    response = await self.connector.call(
                        "Target.attachToTarget",
                        {"targetId": self.target_id, "flatten": True},
                        timeout=20.0
                    )
                    self.session_id = response["sessionId"]
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    await asyncio.sleep(0.3 * (attempt + 1))

            if not self.session_id:
                raise ChromeConnectionError(f"Failed to attach to target {self.target_id}: {last_err}")

            # Optional: Enable Performance domain (some environments need this)
            try:
                await self.connector.call(
                    "Performance.enable",
                    session_id=self.session_id,
                    timeout=15.0
                )
            except Exception:
                # Failure is acceptable; proceed without explicit enable
                pass

            # Enable event listener analysis domains
            try:
                # Always enable Debugger domain and listen to scriptParsed (low cost)
                await self.connector.call(
                    "Debugger.enable", 
                    session_id=self.session_id, 
                    timeout=10.0
                )
                self.connector.on_event("Debugger.scriptParsed", self._on_script_parsed)
                self._event_listener_analysis_enabled = True
                logger.debug("Event listener analysis enabled")
            except Exception as e:
                logger.debug(f"Failed to enable event listener analysis: {e}")
                self._event_listener_analysis_enabled = False

            logger.debug(f"Attached to target {self.target_id} with session {self.session_id}")

            # Enable comprehensive monitoring if requested
            if self.enable_comprehensive:
                await self._enable_comprehensive_monitoring()

            # Status callback notification
            if self.status_callback:
                self.status_callback("site_discovered", {
                    "hostname": self.hostname,
                    "target_id": self.target_id
                })

        except Exception as e:
            raise ChromeConnectionError(f"Failed to attach to target {self.target_id}: {e}")
    
    async def _on_script_parsed(self, params: dict) -> None:
        """Listen to Debugger.scriptParsed events to maintain scriptId->URL mapping."""
        if params.get("sessionId") != self.session_id:
            return
            
        script_id = params.get("scriptId")
        url = params.get("url")
        if script_id and url:
            # Maintain lightweight LRU cache, max 1000 scripts
            if len(self._script_url_cache) >= 1000:
                # Simple FIFO cleanup strategy
                oldest_key = next(iter(self._script_url_cache))
                del self._script_url_cache[oldest_key]
            
            self._script_url_cache[script_id] = url
    
    async def detach(self) -> None:
        """Clean up Target session."""
        # Stop event consumer first
        if self.enable_comprehensive and self.event_consumer_task:
            self.consumer_running = False
            try:
                await asyncio.wait_for(self.event_consumer_task, timeout=1.0)
            except asyncio.TimeoutError:
                self.event_consumer_task.cancel()
                try:
                    await self.event_consumer_task
                except asyncio.CancelledError:
                    pass
            
        # Clean up event listener analysis related resources
        if self._event_listener_analysis_enabled:
            try:
                self.connector.off_event("Debugger.scriptParsed", self._on_script_parsed)
            except Exception as e:
                logger.debug(f"Error cleaning up script parsed event: {e}")
            
            # Cancel detailed analysis task if running
            if self._detailed_analysis_task and not self._detailed_analysis_task.done():
                self._detailed_analysis_task.cancel()
                try:
                    await self._detailed_analysis_task
                except asyncio.CancelledError:
                    pass

        if self.session_id:
            try:
                await self.connector.call(
                    "Target.detachFromTarget",
                    {"sessionId": self.session_id}
                )
                logger.debug(f"Detached from target {self.target_id}")
            except Exception as e:
                # Cleanup errors are acceptable
                logger.debug(f"Error detaching from target {self.target_id}: {e}")
            finally:
                self.session_id = None
    
    async def collect_memory_snapshot(self) -> Dict[str, Any]:
        """Collect memory snapshot - authoritative implementation."""
        if not self.session_id:
            raise ChromeConnectionError("No active session for memory collection")
        
        # Required metrics mapping to output JSON fields
        REQUIRED_METRICS = {
            # memory field mappings
            "JSHeapUsedSize": "memory.jsHeap.used",
            "JSHeapTotalSize": "memory.jsHeap.total",
            "JSEventListeners": "memory.listeners",
            "Documents": "memory.documents",
            "Nodes": "memory.domNodes",
            "Frames": "memory.frames",
            # performance field mappings
            "LayoutCount": "performance.layoutCount",
            "RecalcStyleCount": "performance.recalcStyleCount",
            "LayoutDuration": "performance.layoutDuration",
            "RecalcStyleDuration": "performance.recalcStyleDuration",
            "ScriptDuration": "performance.scriptDuration"
        }
        
        # 1. Get Performance.getMetrics (primary data source)
        metrics_response = await self.connector.call(
            "Performance.getMetrics",
            session_id=self.session_id
        )
        
        # 2. Extract metrics according to the mapping, set missing to null
        extracted = {}
        available_metrics = {m["name"]: m["value"] for m in metrics_response.get("metrics", [])}
        
        for metric_name in REQUIRED_METRICS:
            extracted[metric_name] = available_metrics.get(metric_name, None)
        
        # 3. Optional supplement: get jsHeapSizeLimit only (simplified Runtime.evaluate)
        heap_limit = None
        try:
            limit_result = await self.connector.call(
                "Runtime.evaluate",
                {"expression": "performance.memory?.jsHeapSizeLimit", "returnByValue": True},
                session_id=self.session_id
            )
            heap_limit = limit_result.get("result", {}).get("value")
        except Exception:
            pass  # Keep null on failure
        
        # 4. Build output (using url/title maintained by TabMonitor, no duplicate fetching)
        record = {
            "type": "memory",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hostname": self.hostname,
            "targetId": self.target_id,
            "sessionId": self.session_id,
            "url": self.current_url,
            "title": self.current_title,
            "memory": {
                "jsHeap": {
                    "used": extracted["JSHeapUsedSize"],
                    "total": extracted["JSHeapTotalSize"],
                    "limit": heap_limit  # Optional, null if missing
                },
                "domNodes": extracted["Nodes"],
                "listeners": extracted["JSEventListeners"],
                "documents": extracted["Documents"],
                "frames": extracted["Frames"]
            },
            "performance": {
                "layoutCount": extracted["LayoutCount"],
                "recalcStyleCount": extracted["RecalcStyleCount"],
                "layoutDuration": extracted["LayoutDuration"],
                "recalcStyleDuration": extracted["RecalcStyleDuration"],
                "scriptDuration": extracted["ScriptDuration"]
            }
        }
        
        # 5. Event listener detailed analysis (optional, does not affect existing data)
        try:
            current_listener_count = extracted["JSEventListeners"] or 0
            listeners_analysis = await self._analyze_event_listeners(current_listener_count)
            if listeners_analysis:
                record["eventListenersAnalysis"] = listeners_analysis
        except Exception as e:
            logger.warning(f"Event listener analysis failed: {e}")
            # Failure does not affect main data collection
        
        # Add lightweight event_id for deduplication
        record["event_id"] = make_event_id(
            "memory",
            record.get("hostname", ""),
            record.get("timestamp", ""),
            record.get("targetId", ""),
            record.get("sessionId", ""),
            record.get("url", "")
        )
        return record
    
    async def _analyze_event_listeners(self, current_count: int) -> Optional[Dict[str, Any]]:
        """Analyze event listener details, execute detailed analysis only on abnormal growth."""
        if not self._event_listener_analysis_enabled:
            return None
            
        # 1. Calculate growth delta
        growth_delta = current_count - self._last_listener_count
        self._last_listener_count = current_count
        
        # 2. Lightweight statistics (always execute)
        try:
            basic_stats = await self._get_basic_listener_stats(current_count)
        except Exception as e:
            logger.debug(f"Basic listener stats failed: {e}")
            return None
        
        # 3. Check if detailed analysis is needed (MVP version: simple threshold)
        analysis_result = {
            "summary": basic_stats,
            "growthDelta": growth_delta,
            "analysisTriggered": False
        }
        
        if growth_delta > 20:  # Growth threshold
            # Asynchronously start detailed analysis to avoid blocking sampling cycle
            if not self._detailed_analysis_task or self._detailed_analysis_task.done():
                self._detailed_analysis_task = asyncio.create_task(
                    self._async_detailed_analysis(current_count, basic_stats)
                )
            analysis_result["analysisTriggered"] = True
            
        return analysis_result
    
    async def _get_basic_listener_stats(self, total_from_metrics: int) -> Dict[str, Any]:
        """Get basic listener statistics."""
        # Create dedicated objectGroup to avoid memory leaks
        object_group = f"listener_analysis_{int(datetime.now().timestamp())}"
        
        try:
            # Get document and window objectIds
            doc_result = await self.connector.call(
                "Runtime.evaluate",
                {"expression": "document", "objectGroup": object_group},
                session_id=self.session_id
            )
            win_result = await self.connector.call(
                "Runtime.evaluate",
                {"expression": "window", "objectGroup": object_group},
                session_id=self.session_id
            )
            
            # Get detailed listener information
            doc_listeners_response = await self.connector.call(
                "DOMDebugger.getEventListeners",
                {"objectId": doc_result["result"]["objectId"]},
                session_id=self.session_id
            )
            win_listeners_response = await self.connector.call(
                "DOMDebugger.getEventListeners",
                {"objectId": win_result["result"]["objectId"]},
                session_id=self.session_id
            )
            
            # Correctly access listeners array
            doc_listeners = doc_listeners_response.get("listeners", [])
            win_listeners = win_listeners_response.get("listeners", [])
            
            # Lightweight estimation: elements_total ≈ (JSEventListeners - document - window)
            elements_total = max(0, total_from_metrics - len(doc_listeners) - len(win_listeners))
            
            return {
                "total": len(doc_listeners) + len(win_listeners) + elements_total,
                "byTarget": {
                    "document": len(doc_listeners),
                    "window": len(win_listeners),
                    "elements": elements_total
                },
                "byType": self._group_listeners_by_type(doc_listeners + win_listeners)
            }
            
        finally:
            # Release objectGroup to avoid memory leaks
            try:
                await self.connector.call(
                    "Runtime.releaseObjectGroup",
                    {"objectGroup": object_group},
                    session_id=self.session_id
                )
            except Exception:
                pass
    
    def _group_listeners_by_type(self, listeners: List[Dict[str, Any]]) -> Dict[str, int]:
        """Group listeners by event type."""
        type_counts = defaultdict(int)
        for listener in listeners:
            event_type = listener.get("type", "unknown")
            type_counts[event_type] += 1
        return dict(type_counts)
    
    async def _async_detailed_analysis(self, current_count: int, basic_stats: dict) -> None:
        """Execute detailed analysis asynchronously to avoid blocking memory sampling cycle."""
        try:
            # Enable DOMDebugger domain only when needed
            await self.connector.call(
                "DOMDebugger.enable", 
                session_id=self.session_id, 
                timeout=10.0
            )
            
            # Execute detailed analysis with timeout control
            detailed_sources = await asyncio.wait_for(
                self._perform_detailed_listener_analysis(), timeout=3.0
            )
            
            # Build complete analysis result and send through data_callback
            if detailed_sources and self.data_callback:
                analysis_result = {
                    "type": "memory",  # Still as extension of memory event
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "hostname": self.hostname,
                    "targetId": self.target_id,
                    "sessionId": self.session_id,
                    "eventListenersAnalysis": {
                        "summary": basic_stats,
                        "growthDelta": current_count - self._last_listener_count,
                        "analysisTriggered": True,
                        "detailedSources": detailed_sources
                    }
                }
                
                if asyncio.iscoroutinefunction(self.data_callback):
                    await self.data_callback(analysis_result)
                else:
                    self.data_callback(analysis_result)
                    
        except asyncio.TimeoutError:
            logger.warning("Detailed event listener analysis timeout (3s)")
        except Exception as e:
            logger.warning(f"Detailed event listener analysis failed: {e}")
        finally:
            # Optional: disable DOMDebugger domain to reduce event noise
            try:
                await self.connector.call(
                    "DOMDebugger.disable", 
                    session_id=self.session_id
                )
            except Exception:
                pass
    
    async def _perform_detailed_listener_analysis(self) -> List[Dict[str, Any]]:
        """Detailed listener source analysis - limited candidate sampling to avoid full page scanning."""
        object_group = f"detailed_analysis_{int(datetime.now().timestamp())}"
        
        try:
            # 1. Limited candidate set: avoid full page search, focus on common leak scenarios
            candidate_selectors = [
                "body",  # Page body
                "[role=button]", "button",  # Button elements
                "a[href]",  # Links
                "input", "select", "textarea",  # Form elements
                ".modal", ".dialog", ".popup",  # Modal components
                ".chart-container", ".visualization"  # Visualization components
            ]
            
            candidate_elements = []
            
            # Get first 100 elements of each type, total ≤800 candidates
            for selector in candidate_selectors:
                try:
                    elements_result = await self.connector.call(
                        "Runtime.evaluate",
                        {
                            "expression": f"Array.from(document.querySelectorAll('{selector}')).slice(0, 100)",
                            "objectGroup": object_group
                        },
                        session_id=self.session_id
                    )
                    if elements_result.get("result", {}).get("objectId"):
                        candidate_elements.append(elements_result["result"]["objectId"])
                except Exception:
                    continue  # Skip failed selectors
            
            # 2. Aggregate listeners by source (scriptId+lineNumber)
            sources = defaultdict(lambda: {
                "elementCount": 0,
                "eventTypes": set(),
                "functionName": "",
                "scriptId": "",
                "lineNumber": 0
            })
            
            # Analyze candidate elements' listeners
            for element_array_id in candidate_elements[:300]:  # Limit to max 300 array objects
                try:
                    # Get listeners for each element in the array
                    array_length_result = await self.connector.call(
                        "Runtime.getProperties",
                        {"objectId": element_array_id},
                        session_id=self.session_id
                    )
                    
                    properties = array_length_result.get("result", [])
                    for prop in properties:
                        if prop.get("name", "").isdigit():  # Array index
                            element_id = prop.get("value", {}).get("objectId")
                            if not element_id:
                                continue
                                
                            listeners_response = await self.connector.call(
                                "DOMDebugger.getEventListeners",
                                {"objectId": element_id},
                                session_id=self.session_id
                            )
                            
                            for listener in listeners_response.get("listeners", []):
                                location = listener.get("location", {})
                                script_id = location.get("scriptId")
                                line_number = location.get("lineNumber")
                                
                                if script_id and line_number:
                                    source_key = f"{script_id}:{line_number}"
                                    source_data = sources[source_key]
                                    
                                    source_data["elementCount"] += 1
                                    source_data["eventTypes"].add(listener.get("type", "unknown"))
                                    source_data["scriptId"] = script_id
                                    source_data["lineNumber"] = line_number
                                    source_data["functionName"] = self._extract_function_name(
                                        listener.get("handler", {}).get("description", "")
                                    )
                                    
                except Exception as e:
                    logger.debug(f"Failed to analyze element array: {e}")
                    continue
            
            # 3. Use cached URL mapping, avoid incorrect getScriptSource calls
            result = []
            for source_key, data in sources.items():
                if data["elementCount"] > 1:  # Only focus on functions bound to multiple elements
                    script_id = data["scriptId"]
                    source_file = self._script_url_cache.get(script_id, f"script://{script_id}")
                    
                    result.append({
                        "sourceFile": source_file,
                        "lineNumber": data["lineNumber"],
                        "functionName": data["functionName"][:100],  # Truncate function name
                        "elementCount": data["elementCount"],
                        "eventTypes": list(data["eventTypes"])[:5],  # Limit event types count
                        "suspicion": "high" if data["elementCount"] > 10 else "medium",
                        "scriptId": script_id  # Keep for debugging
                    })
            
            # Sort by element binding count, return top 10 most suspicious sources
            return sorted(result, key=lambda x: x["elementCount"], reverse=True)[:10]
            
        finally:
            # Release all analysis objects
            try:
                await self.connector.call(
                    "Runtime.releaseObjectGroup",
                    {"objectGroup": object_group},
                    session_id=self.session_id
                )
            except Exception:
                pass
    
    def _extract_function_name(self, description: str) -> str:
        """Extract function name from handler description."""
        if not description:
            return "anonymous"
        
        # Try to extract function name from description like "function handleClick() { [code] }"
        description = description.strip()
        if description.startswith("function "):
            # Extract name between "function " and "("
            start_idx = 9  # len("function ")
            end_idx = description.find("(", start_idx)
            if end_idx > start_idx:
                name = description[start_idx:end_idx].strip()
                if name:
                    return name
        elif description.startswith("async function "):
            # Handle async functions
            start_idx = 15  # len("async function ")
            end_idx = description.find("(", start_idx)
            if end_idx > start_idx:
                name = description[start_idx:end_idx].strip()
                if name:
                    return name
        
        # If extraction fails, return truncated description
        return description[:50]
    
    async def start_collection(self, interval: float = 5.0) -> None:
        """Start periodic memory collection."""
        if self.running:
            return
            
        self.running = True
        
        # Initial random jitter to avoid thundering herd
        initial_jitter = random.uniform(0, 1.0)
        await asyncio.sleep(initial_jitter)
        
        while self.running:
            # Wait for next sampling cycle (with small jitter)
            next_interval = interval + random.uniform(-0.1, 0.1)
            await asyncio.sleep(next_interval)
            
            if not self.running:
                break
            
            # Sampling with global concurrency limit + mutex, no busy waiting
            async with SAMPLING_SEMAPHORE:  # Global concurrency limit
                if self._collecting:
                    continue  # Skip this round, not busy waiting (due to sleep)
                
                self._collecting = True
                try:
                    snapshot = await self.collect_memory_snapshot()
                    self.last_activity_time = datetime.now().timestamp()
                    
                    # Check GC metrics if in comprehensive mode
                    if self.enable_comprehensive and self.gc_monitor:
                        try:
                            await self.gc_monitor.check_gc_metrics()
                        except Exception as e:
                            logger.debug(f"GC metrics check failed: {e}")
                    
                    # Fire data callback if set
                    if self.data_callback:
                        try:
                            if asyncio.iscoroutinefunction(self.data_callback):
                                await self.data_callback(snapshot)
                            else:
                                self.data_callback(snapshot)
                        except Exception as e:
                            logger.warning(f"Error in data callback: {e}")
                
                except Exception as e:
                    logger.warning(f"Failed to collect memory snapshot for {self.target_id}: {e}")
                finally:
                    self._collecting = False
    
    async def stop_collection(self) -> None:
        """Stop collection and clean up session."""
        self.running = False
        self.enable_comprehensive = False  # Ensure event consumer can stop
        
        # Stop comprehensive monitoring components
        if self.console_monitor:
            await self.console_monitor.stop_monitoring()
            
        if self.network_monitor:
            await self.network_monitor.stop_monitoring()
        
        if self.domstorage_monitor:
            await self.domstorage_monitor.stop_monitoring()
        
        if self.gc_monitor:
            await self.gc_monitor.stop_monitoring()
        
        # Cancel and wait for event consumer task completion
        if self.event_consumer_task:
            self.event_consumer_task.cancel()
            try:
                await self.event_consumer_task
            except asyncio.CancelledError:
                pass
            self.event_consumer_task = None
        
        # Cancel collection task
        if self.collection_task:
            self.collection_task.cancel()
            try:
                await self.collection_task
            except asyncio.CancelledError:
                pass
            self.collection_task = None
        
        # Ensure Target.detachFromTarget cleanup
        await self.detach()
    
    def update_page_info(self, url: str, title: str) -> None:
        """Update cached page metadata - no CDP evaluate, source from TabMonitor events."""
        self.current_url = url
        self.current_title = title
        self.last_activity_time = datetime.now().timestamp()
    
    async def _enable_comprehensive_monitoring(self):
        """Enable comprehensive monitoring components - queue architecture."""
        # Enable necessary CDP domains
        await self.connector.call("Runtime.enable", session_id=self.session_id)
        await self.connector.call("Network.enable", session_id=self.session_id)
        
        # Create event queue with capacity limit (drop when full)
        self.event_queue = asyncio.Queue(maxsize=1000)
        
        # Import and initialize monitoring components
        from .console import ConsoleMonitor
        from .network import NetworkMonitor
        from .domstorage import DOMStorageMonitor
        from .gc import GCMonitor
        from ..analysis.correlation import SimpleCorrelationEngine
        
        self.console_monitor = ConsoleMonitor(
            self.connector,
            self.session_id,  # Use correct sessionId for filtering
            self.event_queue,
            self.status_callback
        )
        self.network_monitor = NetworkMonitor(
            self.connector,
            self.session_id,  # Use correct sessionId for filtering
            self.event_queue,
            self.status_callback
        )
        self.domstorage_monitor = DOMStorageMonitor(
            self.connector,
            self.session_id,
            self.event_queue,
            self.status_callback
        )
        self.gc_monitor = GCMonitor(
            self.connector,
            self.session_id,
            self.event_queue,
            self.status_callback
        )
        self.correlation_engine = SimpleCorrelationEngine(self.status_callback)
        
        # Set hostname for data grouping
        self.console_monitor.set_hostname(self.hostname)
        self.network_monitor.set_hostname(self.hostname)
        self.domstorage_monitor.set_hostname(self.hostname)
        self.gc_monitor.set_hostname(self.hostname)
        
        # Start monitoring (use queue mode, not data_callback)
        await self.console_monitor.start_monitoring()
        await self.network_monitor.start_monitoring()
        await self.domstorage_monitor.start_monitoring()
        await self.gc_monitor.start_monitoring()
        
        # Start event consumer with independent lifecycle
        self.consumer_running = True
        self.event_consumer_task = asyncio.create_task(self._consume_events())
        
    async def _consume_events(self):
        """Event consumer coroutine - proper stop conditions and lifecycle management."""
        logger.debug(f"Event consumer started for {self.hostname}")
        try:
            while self.consumer_running and self.enable_comprehensive:
                try:
                    # Batch event processing (avoid single event blocking)
                    events_batch = []
                    timeout = 0.1  # 100ms batch window
                    
                    # Collect batch of events
                    try:
                        # Wait for at least one event
                        event_type, event_data = await asyncio.wait_for(
                            self.event_queue.get(), timeout=1.0
                        )
                        logger.debug(f"Got event from queue: {event_type}")
                        events_batch.append((event_type, event_data))
                        
                        # Try to collect more events (non-blocking)
                        end_time = asyncio.get_event_loop().time() + timeout
                        while (asyncio.get_event_loop().time() < end_time and 
                               len(events_batch) < 50):  # Limit batch size
                            try:
                                event_type, event_data = self.event_queue.get_nowait()
                                events_batch.append((event_type, event_data))
                            except asyncio.QueueEmpty:
                                break
                                
                    except asyncio.TimeoutError:
                        continue  # No events, continue loop
                    
                    # Process batch events
                    for event_type, event_data in events_batch:
                        try:
                            # Correlation analysis
                            correlation_result = None
                            if self.correlation_engine:
                                correlation_result = self.correlation_engine.add_event(event_data)
                            
                            # Send original data via single data_callback exit
                            if self.data_callback:
                                if asyncio.iscoroutinefunction(self.data_callback):
                                    await self.data_callback(event_data)
                                else:
                                    self.data_callback(event_data)
                            
                            # Send correlation result (if any)
                            if correlation_result and self.data_callback:
                                if asyncio.iscoroutinefunction(self.data_callback):
                                    await self.data_callback(correlation_result)
                                else:
                                    self.data_callback(correlation_result)
                                    
                        except Exception as e:
                            logger.warning(f"Error processing event {event_type}: {e}")
                            
                except Exception as e:
                    logger.error(f"Error in event consumer loop: {e}")
                    await asyncio.sleep(0.1)  # Avoid tight loop
                    
        except asyncio.CancelledError:
            logger.debug("Event consumer task cancelled")
            raise  # Re-raise to properly cancel task
        except Exception as e:
            logger.error(f"Fatal error in event consumer: {e}")


class MemoryMonitor:
    """Manage multiple tab memory collectors."""
    
    MAX_COLLECTORS = 50
    
    def __init__(self, connector: ChromeConnector):
        self.connector = connector
        self.collectors: Dict[str, MemoryCollector] = {}  # targetId -> collector
        self.data_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    
    async def create_collector(self, target_id: str, hostname: str) -> None:
        """Create memory collector for a target."""
        # Overflow strategy: evict oldest inactive collector
        if len(self.collectors) >= self.MAX_COLLECTORS:
            oldest_id = min(self.collectors.keys(),
                           key=lambda id: self.collectors[id].last_activity_time)
            await self.remove_collector(oldest_id)
            logger.info(f"Evicted oldest collector {oldest_id} due to overflow")
        
        # Create new collector
        collector = MemoryCollector(
            connector=self.connector,
            target_id=target_id,
            hostname=hostname,
            data_callback=self.data_callback
        )
        
        try:
            await collector.attach()
            self.collectors[target_id] = collector
            
            # Start collection in background
            collector.collection_task = asyncio.create_task(collector.start_collection())
            
            logger.debug(f"Created memory collector for {target_id} ({hostname})")
            
        except Exception as e:
            logger.warning(f"Failed to create collector for {target_id}: {e}")
    
    async def remove_collector(self, target_id: str) -> None:
        """Remove and cleanup memory collector."""
        collector = self.collectors.pop(target_id, None)
        if collector:
            try:
                await collector.stop_collection()
                logger.debug(f"Removed memory collector for {target_id}")
            except Exception as e:
                logger.warning(f"Error removing collector {target_id}: {e}")
    
    async def initialize_collectors(self, current_targets: Dict[str, Dict[str, Any]]) -> None:
        """Initialize collectors for existing targets."""
        for target_id, target_info in current_targets.items():
            hostname = target_info.get("hostname")
            if hostname:
                await self.create_collector(target_id, hostname)
                
                # Update page info if available
                collector = self.collectors.get(target_id)
                if collector:
                    collector.update_page_info(
                        target_info.get("url", ""),
                        target_info.get("title", "")
                    )
    
    async def update_collector_page_info(self, target_id: str, url: str, title: str) -> None:
        """Update collector's page information."""
        collector = self.collectors.get(target_id)
        if collector:
            collector.update_page_info(url, title)
    
    def set_data_callback(self, callback: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """Set data callback for all collectors."""
        self.data_callback = callback
        for collector in self.collectors.values():
            collector.data_callback = callback
    
    async def stop_all_collectors(self) -> None:
        """Stop and cleanup all collectors."""
        tasks = []
        for collector in self.collectors.values():
            tasks.append(collector.stop_collection())
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.collectors.clear()
    
    def get_collector_count(self) -> int:
        """Get number of active collectors."""
        return len(self.collectors)
