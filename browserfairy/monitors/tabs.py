"""Tab monitoring functionality."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

from ..core.connector import ChromeConnector


logger = logging.getLogger(__name__)


def extract_hostname(url: str) -> Optional[str]:
    """Extract hostname from URL, filter out noise."""
    try:
        parsed = urlparse(url)
        
        # Filter out non-site URLs
        noise_schemes = {'chrome', 'devtools', 'chrome-extension', 'about', 'data', 'blob', 'edge', 'edge-extension'}
        if parsed.scheme in noise_schemes:
            return None
            
        hostname = parsed.hostname
        if not hostname:
            return None
            
        # Basic hostname cleaning
        hostname = hostname.lower()
        return hostname
        
    except Exception as e:
        logger.warning(f"Error parsing URL {url}: {e}")
        return None


class TabMonitor:
    """Monitor Chrome tabs creation, destruction, and URL changes."""
    
    def __init__(self, connector: ChromeConnector, event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.connector = connector
        self.targets: Dict[str, Dict[str, Any]] = {}  # targetId -> target info
        self.polling_interval = 3.0  # seconds
        self.polling_task: Optional[asyncio.Task] = None
        self.running = False
        self.event_callback = event_callback
        self.targets_lock = asyncio.Lock()  # Protect concurrent access
        
    async def start_monitoring(self) -> None:
        """Start monitoring tab events."""
        if self.running:
            return
            
        self.running = True
        
        # Step 1: Enable target discovery (CRITICAL!)
        await self.connector.set_discover_targets(True)
        
        # Step 2: Register event handlers
        self.connector.on_event("Target.targetCreated", self._on_target_created)
        self.connector.on_event("Target.targetDestroyed", self._on_target_destroyed)  
        self.connector.on_event("Target.targetInfoChanged", self._on_target_info_changed)
        
        # Step 3: Get initial targets (will also trigger targetCreated events)
        await self._sync_targets()
        
        # Step 4: Start polling fallback
        self.polling_task = asyncio.create_task(self._polling_loop())
        
    async def stop_monitoring(self) -> None:
        """Stop monitoring tab events."""
        if not self.running:
            return
            
        self.running = False
        
        # Stop polling
        if self.polling_task:
            self.polling_task.cancel()
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass
            
        # Unregister event handlers
        self.connector.off_event("Target.targetCreated", self._on_target_created)
        self.connector.off_event("Target.targetDestroyed", self._on_target_destroyed)
        self.connector.off_event("Target.targetInfoChanged", self._on_target_info_changed)
        
        # Disable target discovery
        await self.connector.set_discover_targets(False)
        
    async def _on_target_created(self, params: Dict[str, Any]) -> None:
        """Handle Target.targetCreated event."""
        target_info = params.get("targetInfo", {})
        if target_info.get("type") != "page":
            return
            
        target_id = target_info.get("targetId")
        if not target_id:
            return
            
        hostname = extract_hostname(target_info.get("url", ""))
        if not hostname:
            return
            
        # Update internal state with lock protection
        async with self.targets_lock:
            self.targets[target_id] = {
                "targetId": target_id,
                "title": target_info.get("title", ""),
                "url": target_info.get("url", ""),
                "hostname": hostname,
                "browserContextId": target_info.get("browserContextId"),
            }
        
        # Fire callback instead of printing
        await self._fire_event("CREATED", {
            "targetId": target_id,
            "title": target_info.get("title", ""),
            "url": target_info.get("url", ""),
            "hostname": hostname,
            "timestamp": datetime.now().isoformat()
        })
        
    async def _on_target_destroyed(self, params: Dict[str, Any]) -> None:
        """Handle Target.targetDestroyed event."""
        target_id = params.get("targetId")
        if not target_id:
            return
            
        # Remove from internal state with lock protection
        async with self.targets_lock:
            target_info = self.targets.pop(target_id, None)
            
        if not target_info:
            return
            
        # Fire callback instead of printing
        await self._fire_event("DESTROYED", {
            "targetId": target_id,
            "title": target_info["title"],
            "url": target_info["url"],
            "hostname": target_info["hostname"],
            "timestamp": datetime.now().isoformat()
        })
        
    async def _on_target_info_changed(self, params: Dict[str, Any]) -> None:
        """Handle Target.targetInfoChanged event."""
        target_info = params.get("targetInfo", {})
        if target_info.get("type") != "page":
            return
            
        target_id = target_info.get("targetId")
        if not target_id:
            return
            
        hostname = extract_hostname(target_info.get("url", ""))
        if not hostname:
            # Target URL became invalid, remove it
            async with self.targets_lock:
                self.targets.pop(target_id, None)
            return
            
        # Check if this is a meaningful change
        new_url = target_info.get("url", "")
        new_title = target_info.get("title", "")
        
        async with self.targets_lock:
            old_target = self.targets.get(target_id)
            
            if old_target:
                url_changed = old_target["url"] != new_url
                title_changed = old_target["title"] != new_title
                
                if url_changed or title_changed:
                    # Update state
                    self.targets[target_id].update({
                        "title": new_title,
                        "url": new_url,
                        "hostname": hostname,
                        "browserContextId": target_info.get("browserContextId"),
                    })
                    
                    # Fire callback for URL changes (title changes are too noisy)
                    if url_changed:
                        await self._fire_event("URL_CHANGED", {
                            "targetId": target_id,
                            "title": new_title,
                            "url": new_url,
                            "hostname": hostname,
                            "timestamp": datetime.now().isoformat()
                        })
            else:
                # New target not seen before  
                self.targets[target_id] = {
                    "targetId": target_id,
                    "title": new_title,
                    "url": new_url,
                    "hostname": hostname,
                    "browserContextId": target_info.get("browserContextId"),
                }
            
    async def _sync_targets(self) -> None:
        """Sync targets with polling (fallback mechanism)."""
        try:
            response = await self.connector.get_targets()
            current_targets = self.connector.filter_page_targets(response)
            
            # Build set of current target IDs from polling
            current_ids = set()
            
            for target in current_targets:
                target_id = target.get("targetId")
                if not target_id:
                    continue
                    
                hostname = extract_hostname(target.get("url", ""))
                if not hostname:
                    continue
                    
                current_ids.add(target_id)
                
                # Update or add target (polling is the source of truth)  
                async with self.targets_lock:
                    self.targets[target_id] = {
                        "targetId": target_id,
                        "title": target.get("title", ""),
                        "url": target.get("url", ""),
                        "hostname": hostname,
                        "browserContextId": target.get("browserContextId"),
                    }
                
            # Remove targets that no longer exist (eventual consistency)
            async with self.targets_lock:
                stale_ids = set(self.targets.keys()) - current_ids
                for stale_id in stale_ids:
                    stale_target = self.targets.pop(stale_id)
                    logger.debug(f"Removed stale target {stale_id} via polling")
                
        except Exception as e:
            logger.warning(f"Error syncing targets: {e}")
            
    async def _polling_loop(self) -> None:
        """Polling fallback loop for eventual consistency."""
        while self.running:
            try:
                await asyncio.sleep(self.polling_interval)
                if self.running:  # Check again after sleep
                    await self._sync_targets()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error in polling loop: {e}")
                
    async def get_current_targets(self) -> Dict[str, Dict[str, Any]]:
        """Get current targets state (read-only)."""
        async with self.targets_lock:
            return self.targets.copy()
        
    async def get_targets_by_hostname(self, hostname: str) -> List[Dict[str, Any]]:
        """Get targets for a specific hostname."""
        async with self.targets_lock:
            return [target for target in self.targets.values() 
                    if target["hostname"] == hostname]
    
    async def _fire_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Fire event callback if set."""
        if self.event_callback:
            try:
                if asyncio.iscoroutinefunction(self.event_callback):
                    await self.event_callback(event_type, payload)
                else:
                    self.event_callback(event_type, payload)
            except Exception as e:
                logger.warning(f"Error in event callback: {e}")