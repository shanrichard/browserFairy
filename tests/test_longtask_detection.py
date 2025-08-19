"""Tests for long task detection functionality."""

import asyncio
import json
import pytest
import time
from unittest.mock import AsyncMock, Mock
from datetime import datetime, timezone

from browserfairy.core.connector import ChromeConnector
from browserfairy.monitors.memory import MemoryCollector


@pytest.fixture
def mock_connector():
    """Create a mock ChromeConnector."""
    connector = Mock(spec=ChromeConnector)
    connector.call = AsyncMock()
    connector.on_event = Mock()
    connector.off_event = Mock()
    return connector


@pytest.fixture
def longtask_collector(mock_connector):
    """创建启用长任务监控的MemoryCollector"""
    event_queue = asyncio.Queue()
    collector = MemoryCollector(
        mock_connector, "target_123", "example.com",
        enable_comprehensive=True,
        data_callback=None
    )
    collector.session_id = "session_123"
    collector.event_queue = event_queue
    collector.hostname = "example.com"
    collector.target_id = "target_123"
    collector.current_url = "https://example.com/test"
    collector.current_title = "Test Page"
    collector._longtask_timestamps = []
    return collector


class TestLongtaskDetection:
    
    @pytest.mark.asyncio
    async def test_longtask_observer_injection_success(self, longtask_collector):
        """测试PerformanceObserver成功注入"""
        # Mock成功的CDP调用
        longtask_collector.connector.call.return_value = {}
        
        await longtask_collector._inject_longtask_observer()
        
        # 验证正确的CDP调用顺序
        calls = longtask_collector.connector.call.call_args_list
        assert any("Runtime.addBinding" in str(call) for call in calls)
        assert any("Page.enable" in str(call) for call in calls)
        assert any("Page.addScriptToEvaluateOnNewDocument" in str(call) for call in calls)
        assert any("Runtime.evaluate" in str(call) for call in calls)
        
        # 验证状态
        assert longtask_collector.longtask_observer_injected is True
    
    @pytest.mark.asyncio 
    async def test_longtask_observer_injection_failure(self, longtask_collector):
        """测试注入失败时的优雅降级"""
        # Mock错误
        longtask_collector.connector.call.side_effect = Exception("Injection failed")
        
        await longtask_collector._inject_longtask_observer()
        
        # 验证优雅降级
        assert longtask_collector.longtask_observer_injected is False
        # 不应该抛出异常
    
    @pytest.mark.asyncio
    async def test_longtask_data_processing(self, longtask_collector):
        """测试长任务数据处理"""
        # Mock长任务数据（包含attribution信息）
        params = {
            "sessionId": "session_123",
            "name": "__browserFairyLongtaskCallback",
            "payload": json.dumps({
                "timestamp": 1625097600000,
                "startTime": 1000.5,
                "duration": 150.7,
                "name": "task-1",
                "attribution": [
                    {
                        "containerType": "iframe",
                        "containerName": "ads-frame",
                        "containerSrc": "https://ads.example.com/widget.html"
                    }
                ],
                "stack": None  # attribution存在时stack为null
            })
        }
        
        # 处理数据
        await longtask_collector._on_longtask_data(params)
        
        # 验证事件入队
        assert longtask_collector.event_queue.qsize() == 1
        event_type, event_data = longtask_collector.event_queue.get_nowait()
        
        assert event_type == "longtask"
        assert event_data["duration"] == 150.7
        assert event_data["type"] == "longtask"
        assert event_data["sessionId"] == "session_123"
        assert event_data["targetId"] == "target_123"
        assert len(event_data["attribution"]) == 1
        assert event_data["attribution"][0]["containerType"] == "iframe"
        assert event_data["stack"] is None  # attribution存在时无stack
    
    def test_stack_parsing(self, longtask_collector):
        """测试调用栈解析"""
        raw_stack = "Error\n    at func1 (script.js:10:5)\n    at func2 (app.js:25:15)"
        
        result = longtask_collector._process_longtask_stack(raw_stack)
        
        assert result["available"] is True
        assert len(result["frames"]) == 2
        assert result["frames"][0]["functionName"] == "func1"
        assert result["frames"][0]["url"] == "script.js"
        assert result["frames"][0]["lineNumber"] == 10
        assert result["frames"][1]["functionName"] == "func2"
    
    def test_frequency_control(self, longtask_collector):
        """测试长任务频率控制（20 eps）"""
        longtask_collector._longtask_timestamps = []
        
        # 前20个应该通过
        for i in range(20):
            assert longtask_collector._should_emit_longtask_event() is True
        
        # 第21个应该被限制
        assert longtask_collector._should_emit_longtask_event() is False
    
    def test_script_size_limit(self, longtask_collector):
        """测试注入脚本大小限制"""
        script = longtask_collector._build_longtask_observer_script()
        script_size = len(script.encode('utf-8'))
        
        # 验证脚本大小 <1.5KB
        assert script_size < 1536, f"Script size {script_size} exceeds 1536 bytes limit"
        
        # 验证脚本包含必要内容
        assert 'PerformanceObserver' in script
        assert 'JSON.stringify' in script
        assert 'buffered:true' in script or 'buffered: true' in script
        assert '__browserFairyLongtaskObserverInstalled' in script
    
    def test_invalid_longtask_data_handling(self, longtask_collector):
        """测试无效长任务数据处理"""
        # 无效JSON
        invalid_params = {
            "sessionId": "session_123",
            "name": "__browserFairyLongtaskCallback", 
            "payload": "invalid json"
        }
        
        # 不应该抛出异常
        asyncio.run(longtask_collector._on_longtask_data(invalid_params))
        assert longtask_collector.event_queue.qsize() == 0

    def test_session_id_filtering(self, longtask_collector):
        """测试sessionId过滤"""
        wrong_session_params = {
            "sessionId": "wrong_session",
            "name": "__browserFairyLongtaskCallback",
            "payload": json.dumps({"duration": 100})
        }
        
        asyncio.run(longtask_collector._on_longtask_data(wrong_session_params))
        
        # 应该被过滤，不入队
        assert longtask_collector.event_queue.qsize() == 0

    def test_attribution_priority_over_stack(self, longtask_collector):
        """测试attribution优先于stack的逻辑"""
        # 有attribution时，stack应该为null
        params_with_attribution = {
            "sessionId": "session_123",
            "name": "__browserFairyLongtaskCallback",
            "payload": json.dumps({
                "duration": 100,
                "attribution": [{"containerType": "iframe"}],
                "stack": "some stack data"
            })
        }
        
        asyncio.run(longtask_collector._on_longtask_data(params_with_attribution))
        
        # 验证attribution存在时stack为null
        _, event_data = longtask_collector.event_queue.get_nowait()
        assert len(event_data["attribution"]) > 0
        assert event_data["stack"] is None
        
        # 无attribution时，stack应该被处理
        params_no_attribution = {
            "sessionId": "session_123",
            "name": "__browserFairyLongtaskCallback",
            "payload": json.dumps({
                "duration": 100,
                "attribution": [],
                "stack": "Error\n    at test (test.js:1:1)"
            })
        }
        
        asyncio.run(longtask_collector._on_longtask_data(params_no_attribution))
        
        _, event_data = longtask_collector.event_queue.get_nowait()
        assert len(event_data["attribution"]) == 0
        assert event_data["stack"] is not None
        assert event_data["stack"]["available"] is True