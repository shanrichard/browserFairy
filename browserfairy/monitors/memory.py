"""Memory monitoring functionality."""

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from ..core.connector import ChromeConnector, ChromeConnectionError

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
        self.correlation_engine: Optional['SimpleCorrelationEngine'] = None
        self.event_consumer_task: Optional[asyncio.Task] = None
        
    async def attach(self) -> None:
        """Establish Target-level session."""
        try:
            response = await self.connector.call(
                "Target.attachToTarget",
                {"targetId": self.target_id, "flatten": True}
            )
            self.session_id = response["sessionId"]
            
            # Optional: Enable Performance domain (some environments need this)
            try:
                await self.connector.call(
                    "Performance.enable",
                    session_id=self.session_id
                )
            except Exception:
                # Failure is acceptable, not all environments require explicit enable
                pass
                
            logger.debug(f"Attached to target {self.target_id} with session {self.session_id}")
            
            # New: Enable comprehensive monitoring if requested
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
    
    async def detach(self) -> None:
        """Clean up Target session."""
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
        return {
            "type": "memory",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hostname": self.hostname,
            "targetId": self.target_id,
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
        from ..analysis.correlation import SimpleCorrelationEngine
        
        self.console_monitor = ConsoleMonitor(
            self.connector, 
            self.session_id, 
            self.event_queue,
            self.status_callback
        )
        self.network_monitor = NetworkMonitor(
            self.connector, 
            self.session_id, 
            self.event_queue,
            self.status_callback
        )
        self.correlation_engine = SimpleCorrelationEngine(self.status_callback)
        
        # Set hostname for data grouping
        self.console_monitor.set_hostname(self.hostname)
        self.network_monitor.set_hostname(self.hostname)
        
        # Start monitoring (use queue mode, not data_callback)
        await self.console_monitor.start_monitoring()
        await self.network_monitor.start_monitoring()
        
        # Start event consumer
        self.event_consumer_task = asyncio.create_task(self._consume_events())
        
    async def _consume_events(self):
        """Event consumer coroutine - proper stop conditions and lifecycle management."""
        try:
            while self.running and self.enable_comprehensive:
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