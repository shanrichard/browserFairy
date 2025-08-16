"""Tests for memory monitoring functionality."""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone

from browserfairy.core.connector import ChromeConnector, ChromeConnectionError
from browserfairy.monitors.memory import MemoryCollector, MemoryMonitor


@pytest.fixture
def mock_connector():
    """Create a mock ChromeConnector."""
    connector = Mock(spec=ChromeConnector)
    connector.call = AsyncMock()
    return connector


@pytest.fixture
def sample_metrics_response():
    """Sample Performance.getMetrics response."""
    return {
        "metrics": [
            {"name": "JSHeapUsedSize", "value": 45234567},
            {"name": "JSHeapTotalSize", "value": 67890123},
            {"name": "JSEventListeners", "value": 89},
            {"name": "Documents", "value": 1},
            {"name": "Nodes", "value": 1247},
            {"name": "Frames", "value": 2},
            {"name": "LayoutCount", "value": 12},
            {"name": "RecalcStyleCount", "value": 8},
            {"name": "LayoutDuration", "value": 23.4},
            {"name": "RecalcStyleDuration", "value": 15.2},
            {"name": "ScriptDuration", "value": 156.7}
        ]
    }


@pytest.fixture
def sample_heap_limit_response():
    """Sample performance.memory.jsHeapSizeLimit response."""
    return {
        "result": {
            "type": "number",
            "value": 134217728
        }
    }


class TestMemoryCollector:
    """Test MemoryCollector functionality."""
    
    @pytest.mark.asyncio
    async def test_attach_success(self, mock_connector):
        """Test successful target attachment."""
        mock_connector.call.side_effect = [
            {"sessionId": "session123"},  # Target.attachToTarget response
            {}  # Performance.enable response (optional)
        ]
        
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        await collector.attach()
        
        # Verify attach call was made first
        assert mock_connector.call.call_args_list[0] == (
            ("Target.attachToTarget", {"targetId": "target123", "flatten": True}), {}
        )
        assert collector.session_id == "session123"
    
    @pytest.mark.asyncio
    async def test_attach_failure(self, mock_connector):
        """Test attachment failure handling."""
        mock_connector.call.side_effect = Exception("Connection failed")
        
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        
        with pytest.raises(ChromeConnectionError) as exc_info:
            await collector.attach()
        
        assert "Failed to attach to target target123" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_detach(self, mock_connector):
        """Test target detachment."""
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        collector.session_id = "session123"
        
        await collector.detach()
        
        mock_connector.call.assert_called_with(
            "Target.detachFromTarget",
            {"sessionId": "session123"}
        )
        assert collector.session_id is None
    
    @pytest.mark.asyncio
    async def test_collect_memory_snapshot(self, mock_connector, sample_metrics_response, sample_heap_limit_response):
        """Test memory snapshot collection."""
        mock_connector.call.side_effect = [
            sample_metrics_response,  # Performance.getMetrics
            sample_heap_limit_response  # Runtime.evaluate
        ]
        
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        collector.session_id = "session123"
        collector.current_url = "https://example.com/page"
        collector.current_title = "Example Page"
        
        snapshot = await collector.collect_memory_snapshot()
        
        # Verify snapshot structure
        assert snapshot["hostname"] == "example.com"
        assert snapshot["targetId"] == "target123"
        assert snapshot["url"] == "https://example.com/page"
        assert snapshot["title"] == "Example Page"
        assert "timestamp" in snapshot
        
        # Verify timestamp is UTC format
        timestamp = snapshot["timestamp"]
        assert timestamp.endswith("+00:00") or timestamp.endswith("Z")
        # Should be able to parse as ISO format
        parsed_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        assert parsed_dt.tzinfo is not None  # Should have timezone info
        
        # Verify memory data
        memory = snapshot["memory"]
        assert memory["jsHeap"]["used"] == 45234567
        assert memory["jsHeap"]["total"] == 67890123
        assert memory["jsHeap"]["limit"] == 134217728
        assert memory["domNodes"] == 1247
        assert memory["listeners"] == 89
        assert memory["documents"] == 1
        assert memory["frames"] == 2
        
        # Verify performance data
        performance = snapshot["performance"]
        assert performance["layoutCount"] == 12
        assert performance["recalcStyleCount"] == 8
        assert performance["layoutDuration"] == 23.4
        assert performance["recalcStyleDuration"] == 15.2
        assert performance["scriptDuration"] == 156.7
    
    @pytest.mark.asyncio
    async def test_collect_memory_snapshot_missing_metrics(self, mock_connector):
        """Test memory snapshot with missing metrics."""
        # Return empty metrics
        mock_connector.call.side_effect = [
            {"metrics": []},  # Performance.getMetrics
            {"result": {"value": None}}  # Runtime.evaluate (fails)
        ]
        
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        collector.session_id = "session123"
        collector.current_url = "https://example.com/page"
        collector.current_title = "Example Page"
        
        snapshot = await collector.collect_memory_snapshot()
        
        # All metrics should be null when missing
        memory = snapshot["memory"]
        assert memory["jsHeap"]["used"] is None
        assert memory["jsHeap"]["total"] is None
        assert memory["jsHeap"]["limit"] is None
        assert memory["domNodes"] is None
        
        performance = snapshot["performance"]
        assert performance["layoutCount"] is None
        assert performance["scriptDuration"] is None
    
    @pytest.mark.asyncio
    async def test_collect_memory_snapshot_malformed_response(self, mock_connector):
        """Test memory snapshot with malformed metrics response."""
        # Return malformed response without 'metrics' field
        mock_connector.call.side_effect = [
            {},  # Performance.getMetrics with no 'metrics' field
            {"result": {"value": None}}  # Runtime.evaluate
        ]
        
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        collector.session_id = "session123"
        collector.current_url = "https://example.com/page"
        collector.current_title = "Example Page"
        
        snapshot = await collector.collect_memory_snapshot()
        
        # Should handle gracefully - all metrics null when response is malformed
        memory = snapshot["memory"]
        assert memory["jsHeap"]["used"] is None
        assert memory["domNodes"] is None
        
        performance = snapshot["performance"]
        assert performance["layoutCount"] is None
    
    @pytest.mark.asyncio
    async def test_collect_memory_snapshot_no_session(self, mock_connector):
        """Test memory snapshot collection without session."""
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        
        with pytest.raises(ChromeConnectionError) as exc_info:
            await collector.collect_memory_snapshot()
        
        assert "No active session" in str(exc_info.value)
    
    def test_update_page_info(self, mock_connector):
        """Test page info update."""
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        
        collector.update_page_info("https://example.com/new", "New Page")
        
        assert collector.current_url == "https://example.com/new"
        assert collector.current_title == "New Page"
    
    @pytest.mark.asyncio 
    async def test_start_stop_collection(self, mock_connector):
        """Test collection start/stop lifecycle."""
        collector = MemoryCollector(mock_connector, "target123", "example.com")
        collector.session_id = "session123"
        
        # Mock collect_memory_snapshot to avoid actual collection
        collector.collect_memory_snapshot = AsyncMock()
        
        # Start collection
        task = asyncio.create_task(collector.start_collection(interval=0.1))
        
        # Let it run briefly
        await asyncio.sleep(0.05)
        assert collector.running is True
        
        # Stop collection
        await collector.stop_collection()
        
        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        assert collector.running is False


class TestMemoryMonitor:
    """Test MemoryMonitor functionality."""
    
    @pytest.fixture
    def mock_memory_monitor(self, mock_connector):
        """Create a mock MemoryMonitor."""
        return MemoryMonitor(mock_connector)
    
    @pytest.mark.asyncio
    async def test_create_collector(self, mock_memory_monitor):
        """Test collector creation."""
        # Mock the attach method
        with patch.object(MemoryCollector, 'attach', new_callable=AsyncMock):
            await mock_memory_monitor.create_collector("target123", "example.com")
        
        assert "target123" in mock_memory_monitor.collectors
        collector = mock_memory_monitor.collectors["target123"]
        assert collector.target_id == "target123"
        assert collector.hostname == "example.com"
    
    @pytest.mark.asyncio
    async def test_remove_collector(self, mock_memory_monitor):
        """Test collector removal."""
        # Create a mock collector
        mock_collector = Mock()
        mock_collector.stop_collection = AsyncMock()
        mock_memory_monitor.collectors["target123"] = mock_collector
        
        await mock_memory_monitor.remove_collector("target123")
        
        assert "target123" not in mock_memory_monitor.collectors
        mock_collector.stop_collection.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_initialize_collectors(self, mock_memory_monitor):
        """Test collector initialization for existing targets."""
        current_targets = {
            "target1": {"hostname": "example.com", "url": "https://example.com", "title": "Example"},
            "target2": {"hostname": "google.com", "url": "https://google.com", "title": "Google"},
            "target3": {"hostname": None}  # Should be skipped
        }
        
        with patch.object(mock_memory_monitor, 'create_collector', new_callable=AsyncMock) as mock_create:
            await mock_memory_monitor.initialize_collectors(current_targets)
        
        # Should create collectors for targets with hostname
        assert mock_create.call_count == 2
        mock_create.assert_any_call("target1", "example.com")
        mock_create.assert_any_call("target2", "google.com")
    
    @pytest.mark.asyncio
    async def test_collector_overflow_handling(self, mock_memory_monitor):
        """Test collector overflow handling."""
        mock_memory_monitor.MAX_COLLECTORS = 2
        
        # Create mock collectors
        old_collector = Mock()
        old_collector.stop_collection = AsyncMock()
        old_collector.last_activity_time = 1000  # Older
        
        newer_collector = Mock()
        newer_collector.stop_collection = AsyncMock()
        newer_collector.last_activity_time = 2000  # Newer
        
        mock_memory_monitor.collectors = {
            "old_target": old_collector,
            "newer_target": newer_collector
        }
        
        # Create one more collector (should evict oldest)
        with patch.object(MemoryCollector, 'attach', new_callable=AsyncMock):
            await mock_memory_monitor.create_collector("new_target", "example.com")
        
        # Old collector should be removed
        assert "old_target" not in mock_memory_monitor.collectors
        assert "newer_target" in mock_memory_monitor.collectors
        assert "new_target" in mock_memory_monitor.collectors
        old_collector.stop_collection.assert_called_once()
    
    def test_set_data_callback(self, mock_memory_monitor):
        """Test data callback setting."""
        callback = Mock()
        mock_memory_monitor.set_data_callback(callback)
        
        assert mock_memory_monitor.data_callback == callback
    
    @pytest.mark.asyncio
    async def test_stop_all_collectors(self, mock_memory_monitor):
        """Test stopping all collectors."""
        # Create mock collectors
        collector1 = Mock()
        collector1.stop_collection = AsyncMock()
        collector2 = Mock()
        collector2.stop_collection = AsyncMock()
        
        mock_memory_monitor.collectors = {
            "target1": collector1,
            "target2": collector2
        }
        
        await mock_memory_monitor.stop_all_collectors()
        
        # All collectors should be stopped and cleared
        collector1.stop_collection.assert_called_once()
        collector2.stop_collection.assert_called_once()
        assert len(mock_memory_monitor.collectors) == 0
    
    def test_get_collector_count(self, mock_memory_monitor):
        """Test getting collector count."""
        assert mock_memory_monitor.get_collector_count() == 0
        
        # Add some mock collectors
        mock_memory_monitor.collectors = {"target1": Mock(), "target2": Mock()}
        assert mock_memory_monitor.get_collector_count() == 2