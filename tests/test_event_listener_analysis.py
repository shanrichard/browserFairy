"""Tests for event listener analysis functionality in MemoryCollector."""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from browserfairy.monitors.memory import MemoryCollector
from browserfairy.core.connector import ChromeConnector


@pytest.fixture
def mock_connector():
    """Create mock ChromeConnector."""
    connector = MagicMock(spec=ChromeConnector)
    connector.call = AsyncMock()
    connector.on_event = MagicMock()
    connector.off_event = MagicMock()
    return connector


@pytest.fixture
def memory_collector(mock_connector):
    """Create MemoryCollector instance."""
    collector = MemoryCollector(
        connector=mock_connector,
        target_id="test_target_123",
        hostname="example.com",
        data_callback=None
    )
    collector.session_id = "test_session_123"
    return collector


class TestEventListenerAnalysisInitialization:
    """Test event listener analysis initialization and cleanup."""
    
    @pytest.mark.asyncio
    async def test_attach_enables_debugger_domain(self, memory_collector, mock_connector):
        """Test that attach enables Debugger domain and registers event listener."""
        # Mock successful Target.attachToTarget
        mock_connector.call.side_effect = [
            {"sessionId": "test_session_123"},  # Target.attachToTarget
            None,  # Performance.enable
            None   # Debugger.enable
        ]
        
        await memory_collector.attach()
        
        # Verify Debugger domain was enabled
        mock_connector.call.assert_any_call(
            "Debugger.enable",
            session_id="test_session_123",
            timeout=10.0
        )
        
        # Verify event listener was registered
        mock_connector.on_event.assert_any_call(
            "Debugger.scriptParsed", 
            memory_collector._on_script_parsed
        )
        
        # Verify analysis is enabled
        assert memory_collector._event_listener_analysis_enabled is True
    
    @pytest.mark.asyncio
    async def test_attach_handles_debugger_enable_failure(self, memory_collector, mock_connector):
        """Test graceful handling when Debugger.enable fails."""
        # Mock Target.attachToTarget success but Debugger.enable failure
        mock_connector.call.side_effect = [
            {"sessionId": "test_session_123"},  # Target.attachToTarget
            None,  # Performance.enable
            Exception("Debugger not available")  # Debugger.enable fails
        ]
        
        await memory_collector.attach()
        
        # Verify analysis is disabled
        assert memory_collector._event_listener_analysis_enabled is False
    
    @pytest.mark.asyncio
    async def test_detach_cleans_up_event_listener(self, memory_collector, mock_connector):
        """Test that detach properly cleans up event listener analysis."""
        memory_collector._event_listener_analysis_enabled = True
        
        await memory_collector.detach()
        
        # Verify event listener was unregistered
        mock_connector.off_event.assert_called_with(
            "Debugger.scriptParsed",
            memory_collector._on_script_parsed
        )


class TestScriptParsedHandling:
    """Test script parsed event handling and URL caching."""
    
    @pytest.mark.asyncio
    async def test_script_parsed_caches_url(self, memory_collector):
        """Test that scriptParsed events are properly cached."""
        await memory_collector._on_script_parsed({
            "sessionId": "test_session_123",
            "scriptId": "script_123",
            "url": "https://example.com/js/app.js"
        })
        
        # Verify URL was cached
        assert memory_collector._script_url_cache.get("script_123") == "https://example.com/js/app.js"
    
    @pytest.mark.asyncio
    async def test_script_parsed_filters_by_session(self, memory_collector):
        """Test that scriptParsed events are filtered by sessionId."""
        await memory_collector._on_script_parsed({
            "sessionId": "different_session",
            "scriptId": "script_123", 
            "url": "https://example.com/js/app.js"
        })
        
        # Verify URL was not cached
        assert memory_collector._script_url_cache.get("script_123") is None
    
    @pytest.mark.asyncio
    async def test_script_url_cache_lru_cleanup(self, memory_collector):
        """Test that URL cache LRU cleanup works correctly."""
        memory_collector.session_id = "test_session"
        
        # Fill cache by simulating script parsed events (this triggers cleanup logic)
        for i in range(1001):
            await memory_collector._on_script_parsed({
                "sessionId": "test_session",
                "scriptId": f"script_{i}",
                "url": f"https://example.com/script_{i}.js"
            })
        
        # Verify cache size is limited
        assert len(memory_collector._script_url_cache) <= 1000
        # Verify oldest item was removed (script_0 should not exist)
        assert "script_0" not in memory_collector._script_url_cache


class TestBasicListenerStats:
    """Test basic listener statistics collection."""
    
    @pytest.mark.asyncio
    async def test_get_basic_listener_stats_success(self, memory_collector, mock_connector):
        """Test successful basic listener statistics collection."""
        # Mock Runtime.evaluate responses for document and window
        mock_connector.call.side_effect = [
            {"result": {"objectId": "doc_123"}},  # document
            {"result": {"objectId": "win_123"}},  # window
            {"listeners": [{"type": "click"}, {"type": "scroll"}]},  # document listeners
            {"listeners": [{"type": "resize"}]},  # window listeners
            None  # Runtime.releaseObjectGroup
        ]
        
        stats = await memory_collector._get_basic_listener_stats(100)
        
        # Verify stats structure
        assert stats["total"] == 100  # 2 + 1 + 97 (estimated)
        assert stats["byTarget"]["document"] == 2
        assert stats["byTarget"]["window"] == 1
        assert stats["byTarget"]["elements"] == 97
        assert stats["byType"]["click"] == 1
        assert stats["byType"]["scroll"] == 1
        assert stats["byType"]["resize"] == 1
    
    @pytest.mark.asyncio
    async def test_get_basic_listener_stats_object_cleanup(self, memory_collector, mock_connector):
        """Test that objectGroup is properly cleaned up."""
        mock_connector.call.side_effect = [
            {"result": {"objectId": "doc_123"}},
            {"result": {"objectId": "win_123"}},
            {"listeners": []},
            {"listeners": []},
            None  # Runtime.releaseObjectGroup
        ]
        
        await memory_collector._get_basic_listener_stats(50)
        
        # Verify objectGroup was released
        release_calls = [call for call in mock_connector.call.call_args_list 
                        if call[0][0] == "Runtime.releaseObjectGroup"]
        assert len(release_calls) == 1


class TestEventListenerAnalysis:
    """Test main event listener analysis logic."""
    
    @pytest.mark.asyncio
    async def test_analyze_event_listeners_disabled(self, memory_collector):
        """Test analysis returns None when disabled."""
        memory_collector._event_listener_analysis_enabled = False
        
        result = await memory_collector._analyze_event_listeners(100)
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_analyze_event_listeners_no_growth(self, memory_collector, mock_connector):
        """Test analysis with no significant growth."""
        memory_collector._event_listener_analysis_enabled = True
        memory_collector._last_listener_count = 85
        
        # Mock basic stats call
        with patch.object(memory_collector, '_get_basic_listener_stats') as mock_stats:
            mock_stats.return_value = {"total": 100, "byTarget": {}, "byType": {}}
            
            result = await memory_collector._analyze_event_listeners(100)
            
            # Verify result structure
            assert result["growthDelta"] == 15  # 100 - 85
            assert result["analysisTriggered"] is False
            assert "detailedSources" not in result
    
    @pytest.mark.asyncio
    async def test_analyze_event_listeners_triggers_detailed_analysis(self, memory_collector, mock_connector):
        """Test analysis triggers detailed analysis on significant growth."""
        memory_collector._event_listener_analysis_enabled = True
        memory_collector._last_listener_count = 50
        
        with patch.object(memory_collector, '_get_basic_listener_stats') as mock_stats:
            mock_stats.return_value = {"total": 80, "byTarget": {}, "byType": {}}
            
            result = await memory_collector._analyze_event_listeners(80)
            
            # Verify growth triggered detailed analysis
            assert result["growthDelta"] == 30  # 80 - 50 > 20
            assert result["analysisTriggered"] is True
            # Verify async task was created
            assert memory_collector._detailed_analysis_task is not None


class TestDetailedAnalysis:
    """Test detailed listener analysis functionality."""
    
    @pytest.mark.asyncio
    async def test_perform_detailed_listener_analysis_returns_empty_on_failure(self, memory_collector, mock_connector):
        """Test that detailed analysis returns empty list on failure."""
        # Mock all calls to fail
        mock_connector.call.side_effect = Exception("All calls fail")
        
        sources = await memory_collector._perform_detailed_listener_analysis()
        
        # Should return empty list when everything fails
        assert sources == []
    
    @pytest.mark.asyncio
    async def test_perform_detailed_listener_analysis_handles_no_candidates(self, memory_collector, mock_connector):
        """Test handling when no candidate elements are found."""
        # Mock querySelectorAll calls to return empty arrays or fail
        mock_connector.call.side_effect = [
            Exception("No body elements"),  # body
            Exception("No buttons"),        # button
            Exception("No links"),          # a[href]
            Exception("No inputs"),         # input
            Exception("No modals"),         # .modal
            Exception("No charts"),         # .chart-container
            None  # Runtime.releaseObjectGroup
        ]
        
        sources = await memory_collector._perform_detailed_listener_analysis()
        
        # Should return empty list when no candidates found
        assert sources == []
    
    def test_extract_function_name(self, memory_collector):
        """Test function name extraction from handler descriptions."""
        # Test regular function
        name = memory_collector._extract_function_name("function handleClick() { [code] }")
        assert name == "handleClick"
        
        # Test async function
        name = memory_collector._extract_function_name("async function fetchData() { [code] }")
        assert name == "fetchData"
        
        # Test anonymous function
        name = memory_collector._extract_function_name("")
        assert name == "anonymous"
        
        # Test malformed description
        name = memory_collector._extract_function_name("some weird description")
        assert name == "some weird description"[:50]


class TestIntegrationWithMemoryCollection:
    """Test integration with existing memory collection functionality."""
    
    @pytest.mark.asyncio
    async def test_collect_memory_snapshot_with_analysis(self, memory_collector, mock_connector):
        """Test that memory collection includes event listener analysis."""
        memory_collector._event_listener_analysis_enabled = True
        
        # Mock Performance.getMetrics
        mock_connector.call.side_effect = [
            {"metrics": [{"name": "JSEventListeners", "value": 150}]},  # Performance.getMetrics
            None  # Runtime.evaluate for heap limit
        ]
        
        with patch.object(memory_collector, '_analyze_event_listeners') as mock_analyze:
            mock_analyze.return_value = {
                "summary": {"total": 150},
                "growthDelta": 25,
                "analysisTriggered": True
            }
            
            result = await memory_collector.collect_memory_snapshot()
            
            # Verify existing structure is preserved
            assert result["type"] == "memory"
            assert result["memory"]["listeners"] == 150
            
            # Verify analysis was included
            assert "eventListenersAnalysis" in result
            assert result["eventListenersAnalysis"]["growthDelta"] == 25
    
    @pytest.mark.asyncio
    async def test_collect_memory_snapshot_analysis_failure_graceful(self, memory_collector, mock_connector):
        """Test graceful handling when analysis fails."""
        memory_collector._event_listener_analysis_enabled = True
        
        mock_connector.call.side_effect = [
            {"metrics": [{"name": "JSEventListeners", "value": 100}]},
            None
        ]
        
        with patch.object(memory_collector, '_analyze_event_listeners') as mock_analyze:
            mock_analyze.side_effect = Exception("Analysis failed")
            
            result = await memory_collector.collect_memory_snapshot()
            
            # Verify basic memory data is still collected
            assert result["memory"]["listeners"] == 100
            # Analysis failure should not break main collection
            assert "eventListenersAnalysis" not in result


class TestBackwardsCompatibility:
    """Test backwards compatibility with existing functionality."""
    
    @pytest.mark.asyncio
    async def test_memory_collection_without_analysis_unchanged(self, memory_collector, mock_connector):
        """Test that memory collection works unchanged when analysis is disabled."""
        memory_collector._event_listener_analysis_enabled = False
        
        mock_connector.call.side_effect = [
            {"metrics": [{"name": "JSEventListeners", "value": 123}]},
            None
        ]
        
        result = await memory_collector.collect_memory_snapshot()
        
        # Verify existing format is completely unchanged
        assert result["memory"]["listeners"] == 123
        assert "eventListenersAnalysis" not in result
    
    def test_initialization_preserves_existing_attributes(self, memory_collector):
        """Test that new attributes don't interfere with existing ones."""
        # Verify all existing attributes are still present
        assert hasattr(memory_collector, 'connector')
        assert hasattr(memory_collector, 'target_id')
        assert hasattr(memory_collector, 'hostname')
        assert hasattr(memory_collector, 'session_id')
        assert hasattr(memory_collector, 'data_callback')
        
        # Verify new attributes are added
        assert hasattr(memory_collector, '_event_listener_analysis_enabled')
        assert hasattr(memory_collector, '_last_listener_count')
        assert hasattr(memory_collector, '_script_url_cache')
        assert hasattr(memory_collector, '_detailed_analysis_task')
        
        # Verify initial state
        assert memory_collector._event_listener_analysis_enabled is False
        assert memory_collector._last_listener_count == 0
        assert memory_collector._script_url_cache == {}
        assert memory_collector._detailed_analysis_task is None