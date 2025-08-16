"""Tests for tab monitoring functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from browserfairy.monitors.tabs import TabMonitor, extract_hostname
from browserfairy.core.connector import ChromeConnector


class TestExtractHostname:
    """Test hostname extraction function."""
    
    def test_valid_urls(self):
        """Test hostname extraction from valid URLs."""
        assert extract_hostname("https://www.google.com/search") == "www.google.com"
        assert extract_hostname("http://github.com/user/repo") == "github.com"
        assert extract_hostname("https://news.example.com:8080/path") == "news.example.com"
    
    def test_noise_urls(self):
        """Test filtering of noise URLs."""
        assert extract_hostname("chrome://settings/") is None
        assert extract_hostname("devtools://devtools/bundled/devtools_app.html") is None
        assert extract_hostname("chrome-extension://abc123/popup.html") is None
        assert extract_hostname("about:blank") is None
        assert extract_hostname("data:text/html,<h1>Test</h1>") is None
        assert extract_hostname("blob:https://example.com/123") is None
    
    def test_invalid_urls(self):
        """Test handling of invalid URLs."""
        assert extract_hostname("") is None
        assert extract_hostname("not-a-url") is None
        assert extract_hostname("http://") is None
    
    def test_hostname_cleaning(self):
        """Test hostname cleaning (lowercase)."""
        assert extract_hostname("https://EXAMPLE.COM/path") == "example.com"
        assert extract_hostname("HTTPS://WWW.EXAMPLE.COM") == "www.example.com"


class TestTabMonitor:
    """Test TabMonitor class."""
    
    @pytest.fixture
    def mock_connector(self):
        """Create a mock ChromeConnector."""
        connector = MagicMock(spec=ChromeConnector)
        connector.set_discover_targets = AsyncMock()
        connector.get_targets = AsyncMock()
        connector.filter_page_targets = MagicMock()
        connector.on_event = MagicMock()
        connector.off_event = MagicMock()
        return connector
    
    @pytest.fixture
    def monitor(self, mock_connector):
        """Create a TabMonitor instance with mock connector."""
        return TabMonitor(mock_connector)
    
    def test_init(self, monitor, mock_connector):
        """Test TabMonitor initialization."""
        assert monitor.connector == mock_connector
        assert monitor.targets == {}
        assert monitor.polling_interval == 3.0
        assert not monitor.running
    
    @pytest.mark.asyncio
    async def test_start_monitoring(self, monitor, mock_connector):
        """Test starting monitoring enables discovery and registers handlers."""
        mock_connector.get_targets.return_value = {"targetInfos": []}
        mock_connector.filter_page_targets.return_value = []
        
        await monitor.start_monitoring()
        
        # Verify discovery was enabled
        mock_connector.set_discover_targets.assert_called_once_with(True)
        
        # Verify event handlers were registered
        expected_events = ["Target.targetCreated", "Target.targetDestroyed", "Target.targetInfoChanged"]
        for event in expected_events:
            mock_connector.on_event.assert_any_call(event, monitor._on_target_created if "Created" in event 
                                                   else monitor._on_target_destroyed if "Destroyed" in event
                                                   else monitor._on_target_info_changed)
        
        assert monitor.running
        
        # Cleanup
        await monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_stop_monitoring(self, monitor, mock_connector):
        """Test stopping monitoring disables discovery and unregisters handlers."""
        # Start first
        mock_connector.get_targets.return_value = {"targetInfos": []}
        mock_connector.filter_page_targets.return_value = []
        await monitor.start_monitoring()
        
        # Then stop
        await monitor.stop_monitoring()
        
        # Verify discovery was disabled
        mock_connector.set_discover_targets.assert_called_with(False)
        
        # Verify event handlers were unregistered with proper handler functions
        mock_connector.off_event.assert_any_call("Target.targetCreated", monitor._on_target_created)
        mock_connector.off_event.assert_any_call("Target.targetDestroyed", monitor._on_target_destroyed)
        mock_connector.off_event.assert_any_call("Target.targetInfoChanged", monitor._on_target_info_changed)
        
        assert not monitor.running
    
    @pytest.mark.asyncio
    async def test_on_target_created(self, monitor):
        """Test target created event handling."""
        params = {
            "targetInfo": {
                "targetId": "test123",
                "type": "page",
                "title": "Test Page",
                "url": "https://example.com/test",
                "browserContextId": "context1"
            }
        }
        
        await monitor._on_target_created(params)
        
        assert "test123" in monitor.targets
        target = monitor.targets["test123"]
        assert target["hostname"] == "example.com"
        assert target["title"] == "Test Page"
        assert target["url"] == "https://example.com/test"
    
    @pytest.mark.asyncio  
    async def test_on_target_created_filters_non_pages(self, monitor):
        """Test that non-page targets are filtered out."""
        params = {
            "targetInfo": {
                "targetId": "worker123",
                "type": "worker",
                "title": "Worker",
                "url": "https://example.com/worker.js"
            }
        }
        
        await monitor._on_target_created(params)
        
        assert "worker123" not in monitor.targets
    
    @pytest.mark.asyncio
    async def test_on_target_created_filters_noise_urls(self, monitor):
        """Test that noise URLs are filtered out."""
        params = {
            "targetInfo": {
                "targetId": "chrome123",
                "type": "page",
                "title": "Chrome Settings",
                "url": "chrome://settings/"
            }
        }
        
        await monitor._on_target_created(params)
        
        assert "chrome123" not in monitor.targets
    
    @pytest.mark.asyncio
    async def test_on_target_destroyed(self, monitor):
        """Test target destroyed event handling."""
        # First add a target
        monitor.targets["test123"] = {
            "targetId": "test123",
            "hostname": "example.com",
            "title": "Test Page",
            "url": "https://example.com/test"
        }
        
        params = {"targetId": "test123"}
        await monitor._on_target_destroyed(params)
        
        assert "test123" not in monitor.targets
    
    @pytest.mark.asyncio
    async def test_on_target_info_changed_url_change(self, monitor):
        """Test target info changed event for URL changes."""
        # First add a target
        monitor.targets["test123"] = {
            "targetId": "test123",
            "hostname": "example.com",
            "title": "Old Title",
            "url": "https://example.com/old"
        }
        
        params = {
            "targetInfo": {
                "targetId": "test123",
                "type": "page",
                "title": "New Title",
                "url": "https://example.com/new",
                "browserContextId": "context1"
            }
        }
        
        await monitor._on_target_info_changed(params)
        
        target = monitor.targets["test123"]
        assert target["title"] == "New Title"
        assert target["url"] == "https://example.com/new"
    
    @pytest.mark.asyncio
    async def test_get_current_targets(self, monitor):
        """Test getting current targets snapshot."""
        monitor.targets = {
            "test1": {"hostname": "example.com", "title": "Page 1"},
            "test2": {"hostname": "google.com", "title": "Page 2"}
        }
        
        current = await monitor.get_current_targets()
        
        assert len(current) == 2
        assert "test1" in current
        assert "test2" in current
        # Verify it's a copy, not the original
        assert current is not monitor.targets
    
    @pytest.mark.asyncio
    async def test_get_targets_by_hostname(self, monitor):
        """Test getting targets filtered by hostname."""
        monitor.targets = {
            "test1": {"hostname": "example.com", "title": "Page 1"},
            "test2": {"hostname": "google.com", "title": "Page 2"},  
            "test3": {"hostname": "example.com", "title": "Page 3"}
        }
        
        example_targets = await monitor.get_targets_by_hostname("example.com")
        
        assert len(example_targets) == 2
        titles = [t["title"] for t in example_targets]
        assert "Page 1" in titles
        assert "Page 3" in titles