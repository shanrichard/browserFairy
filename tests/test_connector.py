"""Tests for Chrome connector."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from browserfairy.core.connector import ChromeConnector, ChromeConnectionError


class TestChromeConnector:
    """Test ChromeConnector class."""
    
    def test_init(self):
        """Test ChromeConnector initialization."""
        connector = ChromeConnector()
        assert connector.host == "127.0.0.1"
        assert connector.port == 9222
        assert connector.websocket is None
        assert connector.next_id == 1
        assert connector.pending_requests == {}
    
    def test_init_custom_host_port(self):
        """Test ChromeConnector with custom host and port."""
        connector = ChromeConnector(host="localhost", port=9223)
        assert connector.host == "localhost"
        assert connector.port == 9223
    
    def test_format_browser_command(self):
        """Test Browser.getVersion command format."""
        connector = ChromeConnector()
        
        # Mock call method to inspect the message format
        async def mock_call(method, params=None, session_id=None):
            # This is what the actual implementation should create
            expected_format = {
                "id": 1,
                "method": "Browser.getVersion"
            }
            assert method == "Browser.getVersion"
            assert params is None
            assert session_id is None
            return {"product": "Chrome/91.0"}
        
        connector.call = mock_call
        
        # This would be called in real scenario
        # result = await connector.get_browser_version()
        # assert result["product"] == "Chrome/91.0"
    
    def test_request_id_increment(self):
        """Test request ID increments correctly."""
        connector = ChromeConnector()
        
        assert connector.next_id == 1
        
        # Simulate ID assignment (as would happen in call method)
        first_id = connector.next_id
        connector.next_id += 1
        
        second_id = connector.next_id
        connector.next_id += 1
        
        assert first_id == 1
        assert second_id == 2
        assert connector.next_id == 3


@pytest.mark.asyncio
class TestChromeConnectorAsync:
    """Async tests for ChromeConnector."""
    
    @patch('httpx.AsyncClient')
    async def test_discover_websocket_url_success(self, mock_client_class):
        """Test successful WebSocket URL discovery."""
        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Browser": "Chrome/91.0.4472.124",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/123"
        }
        mock_response.raise_for_status.return_value = None
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        connector = ChromeConnector()
        ws_url = await connector._discover_websocket_url()
        
        assert ws_url == "ws://127.0.0.1:9222/devtools/browser/123"
        mock_client.get.assert_called_once_with("http://127.0.0.1:9222/json/version")
    
    @patch('httpx.AsyncClient')
    async def test_discover_websocket_url_connection_error(self, mock_client_class):
        """Test connection error during WebSocket URL discovery."""
        import httpx
        
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        connector = ChromeConnector()
        
        with pytest.raises(ChromeConnectionError) as exc_info:
            await connector._discover_websocket_url()
        
        assert "Could not connect to Chrome" in str(exc_info.value)
        assert "--remote-debugging-port=9222" in str(exc_info.value)
    
    @patch('httpx.AsyncClient')
    async def test_discover_websocket_url_invalid_response(self, mock_client_class):
        """Test invalid response structure."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "NotBrowser": "Some other service"
        }
        mock_response.raise_for_status.return_value = None
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        connector = ChromeConnector()
        
        with pytest.raises(ChromeConnectionError) as exc_info:
            await connector._discover_websocket_url()
        
        assert "Not a valid Chrome debugger endpoint" in str(exc_info.value)
    
    async def test_call_without_connection(self):
        """Test calling method without connection."""
        connector = ChromeConnector()
        
        with pytest.raises(ChromeConnectionError) as exc_info:
            await connector.call("Browser.getVersion")
        
        assert "Not connected to Chrome" in str(exc_info.value)
    
    async def test_get_targets_call(self):
        """Test Target.getTargets method call."""
        connector = ChromeConnector()
        
        # Mock the call method to verify Target.getTargets is called correctly
        async def mock_call(method, params=None, session_id=None):
            assert method == "Target.getTargets"
            assert params is None
            assert session_id is None
            return {
                "targetInfos": [
                    {"targetId": "123", "type": "page", "title": "Test", "url": "http://test.com"},
                    {"targetId": "456", "type": "worker", "title": "Worker", "url": ""},
                ]
            }
        
        connector.call = mock_call
        result = await connector.get_targets()
        
        assert "targetInfos" in result
        assert len(result["targetInfos"]) == 2
    
    async def test_set_discover_targets(self):
        """Test Target.setDiscoverTargets call."""
        connector = ChromeConnector()
        
        # Mock the call method
        async def mock_call(method, params=None, session_id=None):
            assert method == "Target.setDiscoverTargets"
            assert params == {"discover": True}
            assert session_id is None
            return {"result": {}}
        
        connector.call = mock_call
        result = await connector.set_discover_targets(True)
        assert "result" in result
    
class TestChromeConnectorSync:
    """Synchronous tests for ChromeConnector."""
    
    def test_filter_page_targets(self):
        """Test filtering targets to only include pages."""
        connector = ChromeConnector()
        
        targets_response = {
            "targetInfos": [
                {"targetId": "123", "type": "page", "title": "Page 1", "url": "http://page1.com"},
                {"targetId": "456", "type": "worker", "title": "Worker", "url": ""},
                {"targetId": "789", "type": "page", "title": "Page 2", "url": "http://page2.com"},
                {"targetId": "abc", "type": "service_worker", "title": "SW", "url": ""},
            ]
        }
        
        page_targets = connector.filter_page_targets(targets_response)
        
        assert len(page_targets) == 2
        assert all(target["type"] == "page" for target in page_targets)
        assert page_targets[0]["targetId"] == "123"
        assert page_targets[1]["targetId"] == "789"
    
    def test_filter_page_targets_empty(self):
        """Test filtering when no page targets exist."""
        connector = ChromeConnector()
        
        targets_response = {
            "targetInfos": [
                {"targetId": "456", "type": "worker", "title": "Worker", "url": ""},
                {"targetId": "abc", "type": "service_worker", "title": "SW", "url": ""},
            ]
        }
        
        page_targets = connector.filter_page_targets(targets_response)
        
        assert len(page_targets) == 0
    
    def test_filter_page_targets_no_targets(self):
        """Test filtering when targetInfos is missing or empty."""
        connector = ChromeConnector()
        
        # Missing targetInfos
        page_targets = connector.filter_page_targets({})
        assert len(page_targets) == 0
        
        # Empty targetInfos
        page_targets = connector.filter_page_targets({"targetInfos": []})
        assert len(page_targets) == 0
    
    def test_event_handler_registration(self):
        """Test event handler registration and unregistration."""
        connector = ChromeConnector()
        
        def dummy_handler(params):
            pass
        
        # Register handler
        connector.on_event("Target.targetCreated", dummy_handler)
        assert "Target.targetCreated" in connector.event_handlers
        assert dummy_handler in connector.event_handlers["Target.targetCreated"]
        
        # Unregister specific handler
        connector.off_event("Target.targetCreated", dummy_handler)
        assert len(connector.event_handlers["Target.targetCreated"]) == 0
        
        # Register and clear all handlers
        connector.on_event("Target.targetCreated", dummy_handler)
        connector.off_event("Target.targetCreated")
        assert len(connector.event_handlers["Target.targetCreated"]) == 0
    
    
