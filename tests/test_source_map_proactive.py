"""Test proactive source map persistence functionality"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from browserfairy.analysis.source_map import SourceMapResolver


@pytest.mark.asyncio
async def test_persist_all_disabled_by_default():
    """Test that persist_all is disabled by default"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector)
    assert hasattr(resolver, 'persist_all')
    assert resolver.persist_all is False


@pytest.mark.asyncio
async def test_persist_all_enabled():
    """Test that persist_all can be enabled"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector, persist_all=True)
    assert resolver.persist_all is True


@pytest.mark.asyncio
async def test_proactive_persist_not_triggered_when_disabled():
    """Test that proactive persist is not triggered when persist_all is False"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector, persist_all=False)
    resolver.session_id = "test_session"
    resolver.hostname = "test.com"
    
    # Mock the _proactive_persist method to track if it's called
    resolver._proactive_persist = AsyncMock()
    
    # Simulate scriptParsed event with source map
    await resolver._on_script_parsed({
        "sessionId": "test_session",
        "scriptId": "script1",
        "url": "https://test.com/app.js",
        "sourceMapURL": "app.js.map"
    })
    
    # Give async tasks time to run
    await asyncio.sleep(0.1)
    
    # Should not be called when persist_all is False
    resolver._proactive_persist.assert_not_called()


@pytest.mark.asyncio
async def test_proactive_persist_triggered_when_enabled():
    """Test that proactive persist is triggered when persist_all is True"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector, persist_all=True)
    resolver.session_id = "test_session"
    resolver.hostname = "test.com"
    
    # Track created tasks
    created_tasks = []
    original_create_task = asyncio.create_task
    
    def mock_create_task(coro):
        task = original_create_task(coro)
        created_tasks.append(task)
        return task
    
    with patch('asyncio.create_task', side_effect=mock_create_task):
        # Simulate scriptParsed event with source map
        await resolver._on_script_parsed({
            "sessionId": "test_session",
            "scriptId": "script1",
            "url": "https://test.com/app.js",
            "sourceMapURL": "app.js.map"
        })
    
    # Should have created a task for proactive persistence
    assert len(created_tasks) > 0


@pytest.mark.asyncio
async def test_proactive_persist_requires_hostname():
    """Test that proactive persist requires hostname to be set"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector, persist_all=True)
    resolver.session_id = "test_session"
    # Don't set hostname
    
    # Track if _proactive_persist is called
    with patch.object(resolver, '_proactive_persist', new=AsyncMock()) as mock_persist:
        await resolver._on_script_parsed({
            "sessionId": "test_session",
            "scriptId": "script1",
            "url": "https://test.com/app.js",
            "sourceMapURL": "app.js.map"
        })
        
        await asyncio.sleep(0.1)
        
        # Should not be called without hostname
        mock_persist.assert_not_called()


@pytest.mark.asyncio
async def test_download_semaphore_exists():
    """Test that download semaphore is created for concurrency control"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector, persist_all=True)
    
    assert hasattr(resolver, 'download_semaphore')
    assert isinstance(resolver.download_semaphore, asyncio.Semaphore)


@pytest.mark.asyncio
async def test_proactive_persist_handles_errors():
    """Test that proactive persist handles download errors gracefully"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector, persist_all=True)
    resolver.session_id = "test_session"
    resolver.hostname = "test.com"
    
    # Mock _get_source_map to raise an exception
    with patch.object(resolver, '_get_source_map', side_effect=Exception("Download failed")):
        # This should not raise an exception
        await resolver._proactive_persist("script1", "https://test.com/app.js", "app.js.map")
    
    # Test passes if no exception is raised


@pytest.mark.asyncio
async def test_proactive_persist_respects_semaphore():
    """Test that proactive persist respects the download semaphore"""
    mock_connector = MagicMock()
    resolver = SourceMapResolver(mock_connector, persist_all=True)
    resolver.session_id = "test_session"
    resolver.hostname = "test.com"
    resolver.download_semaphore = asyncio.Semaphore(1)  # Limit to 1 concurrent download
    
    download_count = 0
    max_concurrent = 0
    current_concurrent = 0
    
    async def mock_get_source_map(*args):
        nonlocal download_count, max_concurrent, current_concurrent
        current_concurrent += 1
        max_concurrent = max(max_concurrent, current_concurrent)
        await asyncio.sleep(0.1)  # Simulate download time
        current_concurrent -= 1
        download_count += 1
        return {"mock": "source_map"}
    
    with patch.object(resolver, '_get_source_map', side_effect=mock_get_source_map):
        # Start multiple downloads concurrently
        tasks = [
            asyncio.create_task(resolver._proactive_persist(f"script{i}", f"https://test.com/app{i}.js", f"app{i}.js.map"))
            for i in range(3)
        ]
        
        await asyncio.gather(*tasks)
        
        # Should have downloaded all, but max concurrent should be 1
        assert download_count == 3
        assert max_concurrent == 1  # Semaphore should limit to 1