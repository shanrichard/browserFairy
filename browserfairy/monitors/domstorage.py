"""DOMStorage (localStorage/sessionStorage) monitoring for comprehensive mode."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from ..core.connector import ChromeConnector

logger = logging.getLogger(__name__)


class DOMStorageMonitor:
    """Listen to DOMStorage events and enqueue normalized records."""

    def __init__(self, connector: ChromeConnector, session_id: str,
                 event_queue: asyncio.Queue, status_callback: Optional[callable] = None):
        self.connector = connector
        self.session_id = session_id
        self.event_queue = event_queue
        self.status_callback = status_callback
        self.hostname: Optional[str] = None

    def set_hostname(self, hostname: str) -> None:
        self.hostname = hostname

    async def start_monitoring(self) -> None:
        # Enable DOMStorage domain for this session
        try:
            await self.connector.call("DOMStorage.enable", session_id=self.session_id)
        except Exception as e:
            logger.debug(f"DOMStorage.enable failed (non-fatal): {e}")

        # Register event handlers
        self.connector.on_event("DOMStorage.domStorageItemAdded", self._on_added)
        self.connector.on_event("DOMStorage.domStorageItemRemoved", self._on_removed)
        self.connector.on_event("DOMStorage.domStorageItemUpdated", self._on_updated)
        self.connector.on_event("DOMStorage.domStorageItemsCleared", self._on_cleared)

    async def stop_monitoring(self) -> None:
        self.connector.off_event("DOMStorage.domStorageItemAdded", self._on_added)
        self.connector.off_event("DOMStorage.domStorageItemRemoved", self._on_removed)
        self.connector.off_event("DOMStorage.domStorageItemUpdated", self._on_updated)
        self.connector.off_event("DOMStorage.domStorageItemsCleared", self._on_cleared)

    def _normalize_id(self, storage_id: dict) -> dict:
        origin = (storage_id or {}).get("securityOrigin", "")
        is_local = bool((storage_id or {}).get("isLocalStorage", False))
        return {"origin": origin, "isLocalStorage": is_local}

    async def _enqueue(self, record_type: str, data: dict) -> None:
        data.update({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": record_type,
            "hostname": self.hostname
        })
        try:
            self.event_queue.put_nowait((record_type, data))
        except asyncio.QueueFull:
            logger.warning("DOMStorage event queue full, dropping event")

    async def _on_added(self, params: dict) -> None:
        if params.get("sessionId") != self.session_id:
            return
        await self._enqueue("domstorage_added", {
            "storage": self._normalize_id(params.get("storageId", {})),
            "key": params.get("key", ""),
            "newValue": params.get("newValue", "")
        })

    async def _on_removed(self, params: dict) -> None:
        if params.get("sessionId") != self.session_id:
            return
        await self._enqueue("domstorage_removed", {
            "storage": self._normalize_id(params.get("storageId", {})),
            "key": params.get("key", "")
        })

    async def _on_updated(self, params: dict) -> None:
        if params.get("sessionId") != self.session_id:
            return
        await self._enqueue("domstorage_updated", {
            "storage": self._normalize_id(params.get("storageId", {})),
            "key": params.get("key", ""),
            "oldValue": params.get("oldValue", ""),
            "newValue": params.get("newValue", "")
        })

    async def _on_cleared(self, params: dict) -> None:
        if params.get("sessionId") != self.session_id:
            return
        await self._enqueue("domstorage_cleared", {
            "storage": self._normalize_id(params.get("storageId", {}))
        })

