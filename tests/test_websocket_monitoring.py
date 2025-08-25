"""Tests for WebSocket monitoring functionality in NetworkMonitor."""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from browserfairy.monitors.network import NetworkMonitor
from browserfairy.core.connector import ChromeConnector


@pytest.fixture
def mock_connector():
    """Create mock ChromeConnector."""
    connector = MagicMock(spec=ChromeConnector)
    connector.on_event = MagicMock()
    connector.off_event = MagicMock()
    return connector


@pytest.fixture
def event_queue():
    """Create event queue."""
    return asyncio.Queue(maxsize=100)


@pytest.fixture
def network_monitor(mock_connector, event_queue):
    """Create NetworkMonitor instance."""
    monitor = NetworkMonitor(
        connector=mock_connector,
        session_id="test_session_123",
        target_id="test_target_abc",
        event_queue=event_queue,
        status_callback=None
    )
    monitor.set_hostname("example.com")
    return monitor


class TestWebSocketEventRegistration:
    """Test WebSocket event registration and cleanup."""
    
    @pytest.mark.asyncio
    async def test_start_monitoring_registers_websocket_events(self, network_monitor, mock_connector):
        """Test that start_monitoring registers WebSocket event handlers."""
        await network_monitor.start_monitoring()
        
        # Verify WebSocket events are registered
        expected_calls = [
            ("Network.webSocketCreated", network_monitor._on_websocket_created),
            ("Network.webSocketFrameSent", network_monitor._on_websocket_frame_sent),
            ("Network.webSocketFrameReceived", network_monitor._on_websocket_frame_received),
            ("Network.webSocketFrameError", network_monitor._on_websocket_frame_error),
            ("Network.webSocketClosed", network_monitor._on_websocket_closed),
        ]
        
        for event_name, handler in expected_calls:
            mock_connector.on_event.assert_any_call(event_name, handler)
    
    @pytest.mark.asyncio
    async def test_stop_monitoring_unregisters_websocket_events(self, network_monitor, mock_connector):
        """Test that stop_monitoring unregisters WebSocket event handlers."""
        await network_monitor.stop_monitoring()
        
        # Verify WebSocket events are unregistered
        expected_calls = [
            ("Network.webSocketCreated", network_monitor._on_websocket_created),
            ("Network.webSocketFrameSent", network_monitor._on_websocket_frame_sent),
            ("Network.webSocketFrameReceived", network_monitor._on_websocket_frame_received),
            ("Network.webSocketFrameError", network_monitor._on_websocket_frame_error),
            ("Network.webSocketClosed", network_monitor._on_websocket_closed),
        ]
        
        for event_name, handler in expected_calls:
            mock_connector.off_event.assert_any_call(event_name, handler)


class TestWebSocketCreated:
    """Test WebSocket connection created events."""
    
    @pytest.mark.asyncio
    async def test_websocket_created_event(self, network_monitor, event_queue):
        """Test WebSocket created event processing."""
        params = {
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "url": "wss://example.com/live"
        }
        
        await network_monitor._on_websocket_created(params)
        
        # Check connection is stored
        assert "ws_123" in network_monitor.websocket_connections
        connection_info = network_monitor.websocket_connections["ws_123"]
        assert connection_info["url"] == "wss://example.com/live"
        assert "created_at" in connection_info
        
        # Check event is queued
        assert event_queue.qsize() == 1
        event_type, event_data = await event_queue.get()
        
        assert event_type == "websocket_created"
        assert event_data["type"] == "websocket_created"
        assert event_data["requestId"] == "ws_123"
        assert event_data["url"] == "wss://example.com/live"
        assert event_data["hostname"] == "example.com"
        assert event_data["sessionId"] == "test_session_123"
        assert "event_id" in event_data
    
    @pytest.mark.asyncio
    async def test_websocket_created_session_filtering(self, network_monitor, event_queue):
        """Test that WebSocket created events are filtered by sessionId."""
        params = {
            "sessionId": "different_session",
            "requestId": "ws_123",
            "url": "wss://example.com/live"
        }
        
        await network_monitor._on_websocket_created(params)
        
        # Should not store connection or queue event
        assert "ws_123" not in network_monitor.websocket_connections
        assert event_queue.qsize() == 0


class TestWebSocketFrames:
    """Test WebSocket frame events."""
    
    @pytest.mark.asyncio
    async def test_websocket_frame_sent_text(self, network_monitor, event_queue):
        """Test WebSocket text frame sent event."""
        # First create connection
        await network_monitor._on_websocket_created({
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "url": "wss://example.com/live"
        })
        
        # Clear the created event from queue
        await event_queue.get()
        
        # Send text frame
        params = {
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "response": {
                "opcode": 1,  # Text frame
                "payloadData": "Hello WebSocket"
            }
        }
        
        await network_monitor._on_websocket_frame_sent(params)
        
        # Check event is queued
        assert event_queue.qsize() == 1
        event_type, event_data = await event_queue.get()
        
        assert event_type == "websocket_frame_sent"
        assert event_data["type"] == "websocket_frame_sent"
        assert event_data["requestId"] == "ws_123"
        assert event_data["url"] == "wss://example.com/live"
        assert event_data["opcode"] == 1
        assert event_data["payloadLength"] == 15
        assert event_data["payloadText"] == "Hello WebSocket"
        assert "frameStats" in event_data
        assert "event_id" in event_data
    
    @pytest.mark.asyncio
    async def test_websocket_frame_received_binary(self, network_monitor, event_queue):
        """Test WebSocket binary frame received event."""
        # First create connection
        await network_monitor._on_websocket_created({
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "url": "wss://example.com/live"
        })
        
        # Clear the created event from queue
        await event_queue.get()
        
        # Receive binary frame
        params = {
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "response": {
                "opcode": 2,  # Binary frame
                "payloadData": "binary_data_representation"
            }
        }
        
        await network_monitor._on_websocket_frame_received(params)
        
        # Check event is queued
        assert event_queue.qsize() == 1
        event_type, event_data = await event_queue.get()
        
        assert event_type == "websocket_frame_received"
        assert event_data["opcode"] == 2
        assert event_data["payloadLength"] == 26
        assert event_data["payloadType"] == "binary"
        assert "payloadText" not in event_data  # No text content for binary
    
    @pytest.mark.asyncio
    async def test_websocket_frame_large_text_truncation(self, network_monitor, event_queue):
        """Test that large text frames are properly truncated."""
        # First create connection
        await network_monitor._on_websocket_created({
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "url": "wss://example.com/live"
        })
        
        # Clear the created event from queue
        await event_queue.get()
        
        # Send large text frame
        large_text = "x" * 2000  # 2000 characters
        params = {
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "response": {
                "opcode": 1,
                "payloadData": large_text
            }
        }
        
        await network_monitor._on_websocket_frame_sent(params)
        
        event_type, event_data = await event_queue.get()
        
        # Should be truncated to 1024 chars + truncation marker
        assert len(event_data["payloadText"]) == 1024 + len("...[truncated]")
        assert event_data["payloadText"].endswith("...[truncated]")
        assert event_data["payloadLength"] == 2000  # Original length
    
    @pytest.mark.asyncio
    async def test_websocket_frame_session_filtering(self, network_monitor, event_queue):
        """Test that WebSocket frame events are filtered by sessionId."""
        params = {
            "sessionId": "different_session",
            "requestId": "ws_123",
            "response": {
                "opcode": 1,
                "payloadData": "Hello WebSocket"
            }
        }
        
        await network_monitor._on_websocket_frame_sent(params)
        
        # Should not queue event
        assert event_queue.qsize() == 0


class TestWebSocketClosed:
    """Test WebSocket connection closed events."""
    
    @pytest.mark.asyncio
    async def test_websocket_closed_event(self, network_monitor, event_queue):
        """Test WebSocket closed event processing."""
        # First create connection
        await network_monitor._on_websocket_created({
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "url": "wss://example.com/live"
        })
        
        # Clear the created event from queue
        await event_queue.get()
        
        # Close connection
        params = {
            "sessionId": "test_session_123",
            "requestId": "ws_123"
        }
        
        await network_monitor._on_websocket_closed(params)
        
        # Check connection is cleaned up
        assert "ws_123" not in network_monitor.websocket_connections
        
        # Check event is queued
        assert event_queue.qsize() == 1
        event_type, event_data = await event_queue.get()
        
        assert event_type == "websocket_closed"
        assert event_data["type"] == "websocket_closed"
        assert event_data["requestId"] == "ws_123"
        assert event_data["url"] == "wss://example.com/live"


class TestWebSocketFrameError:
    """Test WebSocket frame error events."""
    
    @pytest.mark.asyncio
    async def test_websocket_frame_error_event(self, network_monitor, event_queue):
        """Test WebSocket frame error event processing."""
        # First create connection
        await network_monitor._on_websocket_created({
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "url": "wss://example.com/live"
        })
        
        # Clear the created event from queue
        await event_queue.get()
        
        # Frame error
        params = {
            "sessionId": "test_session_123",
            "requestId": "ws_123",
            "errorMessage": "WebSocket frame decode error"
        }
        
        await network_monitor._on_websocket_frame_error(params)
        
        # Check event is queued
        assert event_queue.qsize() == 1
        event_type, event_data = await event_queue.get()
        
        assert event_type == "websocket_frame_error"
        assert event_data["type"] == "websocket_frame_error"
        assert event_data["requestId"] == "ws_123"
        assert event_data["url"] == "wss://example.com/live"
        assert event_data["errorMessage"] == "WebSocket frame decode error"


class TestFrameStats:
    """Test WebSocket frame statistics."""
    
    def test_frame_stats_calculation(self, network_monitor):
        """Test frame statistics calculation."""
        url = "wss://example.com/live"
        connection_age = 30.5
        
        stats = network_monitor._get_frame_stats(url, connection_age)
        
        assert "framesThisSecond" in stats
        assert "connectionAge" in stats
        assert stats["connectionAge"] == 30.5
        assert isinstance(stats["framesThisSecond"], int)
    
    def test_frame_stats_aggregation(self, network_monitor):
        """Test that frame stats aggregate correctly."""
        url = "wss://example.com/live"
        
        # Call multiple times in same second
        stats1 = network_monitor._get_frame_stats(url, 10.0)
        stats2 = network_monitor._get_frame_stats(url, 10.0)
        stats3 = network_monitor._get_frame_stats(url, 10.0)
        
        # Should increment counter
        assert stats3["framesThisSecond"] >= 3


class TestBackwardsCompatibility:
    """Test that WebSocket monitoring doesn't break existing HTTP monitoring."""
    
    @pytest.mark.asyncio
    async def test_http_monitoring_still_works(self, network_monitor, event_queue, mock_connector):
        """Test that existing HTTP monitoring is unaffected."""
        # Simulate HTTP request event
        http_params = {
            "sessionId": "test_session_123",
            "requestId": "http_123",
            "request": {
                "url": "https://example.com/api/test",
                "method": "GET",
                "headers": {},
                "postData": ""
            },
            "initiator": {"type": "script"},
            "timestamp": 1234567.89
        }
        
        await network_monitor._on_request_start(http_params)
        
        # Should still work and queue HTTP event
        assert event_queue.qsize() == 1
        event_type, event_data = await event_queue.get()
        
        assert event_type == "network_request_start"
        assert event_data["type"] == "network_request_start"
        assert event_data["url"] == "https://example.com/api/test"
        assert event_data["method"] == "GET"
    
    def test_websocket_attributes_initialization(self, network_monitor):
        """Test that WebSocket attributes are properly initialized."""
        assert hasattr(network_monitor, 'websocket_connections')
        assert hasattr(network_monitor, 'websocket_frame_stats')
        assert isinstance(network_monitor.websocket_connections, dict)
        assert isinstance(network_monitor.websocket_frame_stats, dict)
        assert len(network_monitor.websocket_connections) == 0
        assert len(network_monitor.websocket_frame_stats) == 0
