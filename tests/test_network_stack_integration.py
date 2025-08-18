"""网络请求调用栈关联功能的集成测试"""

import asyncio
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from browserfairy.monitors.network import NetworkMonitor


class TestNetworkStackIntegration:
    """端到端集成测试，验证完整的栈收集工作流程"""
    
    @pytest.fixture 
    def mock_connector(self):
        """Mock ChromeConnector"""
        connector = AsyncMock()
        # Mock successful Debugger enable
        connector.call.return_value = {}
        return connector
    
    @pytest.fixture
    def network_monitor(self, mock_connector):
        """创建NetworkMonitor实例"""
        event_queue = asyncio.Queue()
        monitor = NetworkMonitor(mock_connector, "test_session", event_queue)
        return monitor, event_queue
    
    @pytest.mark.asyncio
    async def test_large_request_detailed_stack_collection(self, network_monitor):
        """测试大请求的完整栈收集流程"""
        monitor, event_queue = network_monitor
        
        # 启动监控（应该启用Debugger）
        await monitor.start_monitoring()
        assert monitor.debugger_enabled is True
        
        # 模拟大文件上传请求开始
        large_upload_params = {
            "sessionId": "test_session",
            "requestId": "req_large_upload",
            "type": "XHR",
            "request": {
                "url": "https://api.com/upload/large",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "postData": "x" * (102400 + 1)  # 100KB + 1
            },
            "initiator": {
                "type": "script",
                "stack": {
                    "callFrames": [
                        {
                            "functionName": "uploadLargeFile",
                            "url": "https://app.js",
                            "lineNumber": 42,
                            "columnNumber": 15,
                            "scriptId": "123"
                        },
                        {
                            "functionName": "handleSubmit",
                            "url": "https://app.js", 
                            "lineNumber": 28,
                            "columnNumber": 8,
                            "scriptId": "123"
                        }
                    ],
                    "parent": {
                        "callFrames": [
                            {
                                "functionName": "onclick",
                                "url": "https://main.js",
                                "lineNumber": 156,
                                "columnNumber": 4,
                                "scriptId": "124"
                            }
                        ]
                    }
                }
            },
            "timestamp": 12345.678
        }
        
        # 处理请求开始
        await monitor._on_request_start(large_upload_params)
        
        # 验证候选已被缓存（因为是大上传）
        assert "req_large_upload" in monitor.stack_candidates
        candidate = monitor.stack_candidates["req_large_upload"]
        assert candidate["resource_type"] == "XHR"
        assert "snapshot" in candidate
        
        # 验证计数已更新
        assert monitor.api_count[("https://api.com", "/upload/large")] == 1
        
        # 模拟请求完成（大响应）
        finish_params = {
            "sessionId": "test_session",
            "requestId": "req_large_upload",
            "encodedDataLength": 5242880,  # 5MB 响应
            "timestamp": 12350.123
        }
        
        # 处理请求完成
        await monitor._on_request_finished(finish_params)
        
        # 验证栈候选被清理
        assert "req_large_upload" not in monitor.stack_candidates
        
        # 先跳过start事件，获取completion事件
        start_event = await event_queue.get()
        assert start_event[0] == "network_request_start"
        
        completion_event = await event_queue.get()
        assert completion_event[0] == "network_request_complete"
        request_data = completion_event[1]
        
        # 验证详细栈字段存在且enabled
        assert "detailedStack" in request_data
        detailed_stack = request_data["detailedStack"]
        assert detailed_stack["enabled"] is True
        assert detailed_stack["reason"] == "large_download"
        assert "frames" in detailed_stack
        assert "asyncFrames" in detailed_stack
        assert len(detailed_stack["frames"]) == 2  # 主栈2帧
        assert len(detailed_stack["asyncFrames"]) == 1  # 异步栈1帧
        
        # 验证栈内容正确
        frames = detailed_stack["frames"]
        assert frames[0]["functionName"] == "uploadLargeFile"
        assert frames[1]["functionName"] == "handleSubmit"
        
        async_frames = detailed_stack["asyncFrames"]
        assert async_frames[0]["functionName"] == "onclick"
        
        # 验证调试统计更新
        stats = monitor.get_debug_stats()
        assert stats["lifetime_stats"]["total_stacks_collected"] == 1
        assert len(stats["recent_triggers"]) == 1
        assert stats["recent_triggers"][0]["enabled"] is True

    @pytest.mark.asyncio
    async def test_small_request_performance_unchanged(self, network_monitor):
        """测试小请求性能完全不受影响"""
        monitor, event_queue = network_monitor
        
        await monitor.start_monitoring()
        
        # 模拟小请求
        small_request_params = {
            "sessionId": "test_session",
            "requestId": "req_small",
            "type": "XHR",
            "request": {
                "url": "https://api.com/status", 
                "method": "GET",
                "headers": {},
                "postData": ""  # 无数据
            },
            "initiator": {
                "type": "script",
                "stack": {
                    "callFrames": [
                        {"functionName": "checkStatus", "url": "https://app.js", "lineNumber": 10}
                    ]
                }
            },
            "timestamp": 12345.678
        }
        
        await monitor._on_request_start(small_request_params)
        
        # 验证候选被缓存（所有XHR都会被缓存为候选）
        assert "req_small" in monitor.stack_candidates
        
        # 模拟小响应完成
        finish_params = {
            "sessionId": "test_session",
            "requestId": "req_small", 
            "encodedDataLength": 512,  # 小响应
            "timestamp": 12346.123
        }
        
        await monitor._on_request_finished(finish_params)
        
        # 先跳过start事件，获取completion事件  
        start_event = await event_queue.get()
        assert start_event[0] == "network_request_start"
        
        completion_event = await event_queue.get()
        request_data = completion_event[1]
        
        # 验证小请求没有详细栈（不满足触发条件）
        assert "detailedStack" not in request_data
        
        # 验证候选被清理
        assert "req_small" not in monitor.stack_candidates

    @pytest.mark.asyncio
    async def test_high_frequency_api_trigger(self, network_monitor):
        """测试高频API调用触发栈收集"""
        monitor, event_queue = network_monitor
        await monitor.start_monitoring()
        
        # 模拟51次API调用同一端点
        api_url = "https://trading-api.com/v2/trades"
        for i in range(51):
            params = {
                "sessionId": "test_session", 
                "requestId": f"req_api_{i}",
                "type": "Fetch",
                "request": {"url": api_url, "method": "GET", "headers": {}},
                "initiator": {
                    "type": "script",
                    "stack": {
                        "callFrames": [
                            {"functionName": "fetchTrades", "url": "https://trader.js", "lineNumber": 100}
                        ]
                    }
                },
                "timestamp": 12345.0 + i
            }
            await monitor._on_request_start(params)
            
            # 模拟正常响应完成
            finish_params = {
                "sessionId": "test_session",
                "requestId": f"req_api_{i}",
                "encodedDataLength": 5000,  # 正常大小
                "timestamp": 12345.1 + i
            }
            await monitor._on_request_finished(finish_params)
            
            # 清空队列中的事件
            try:
                while True:
                    await asyncio.wait_for(event_queue.get(), timeout=0.001)
            except asyncio.TimeoutError:
                pass
        
        # 验证API计数达到51
        assert monitor.api_count[("https://trading-api.com", "/v2/trades")] == 51
        
        # 再发一次请求，这次应该触发详细栈
        final_params = {
            "sessionId": "test_session",
            "requestId": "req_api_final", 
            "type": "Fetch",
            "request": {"url": api_url, "method": "GET", "headers": {}},
            "initiator": {
                "type": "script",
                "stack": {
                    "callFrames": [
                        {"functionName": "fetchTrades", "url": "https://trader.js", "lineNumber": 100}
                    ]
                }
            },
            "timestamp": 12400.0
        }
        await monitor._on_request_start(final_params)
        
        # 正常响应但会因为高频触发详细栈
        final_finish = {
            "sessionId": "test_session",
            "requestId": "req_api_final",
            "encodedDataLength": 5000,
            "timestamp": 12400.1
        }
        await monitor._on_request_finished(final_finish)
        
        # 先跳过start事件，获取最终completion事件
        start_event = await event_queue.get()
        assert start_event[0] == "network_request_start"
        
        completion_event = await event_queue.get()
        request_data = completion_event[1]
        
        # 验证详细栈被触发
        assert "detailedStack" in request_data
        detailed_stack = request_data["detailedStack"]
        assert detailed_stack["enabled"] is True
        assert "high_frequency_api_52" in detailed_stack["reason"]

    @pytest.mark.asyncio
    async def test_debugger_failure_graceful_degradation(self, network_monitor):
        """测试Debugger启用失败的优雅降级"""
        monitor, event_queue = network_monitor
        
        # Mock Debugger.enable失败
        monitor.connector.call.side_effect = Exception("Debugger not available")
        
        # 启动监控不应该抛出异常
        await monitor.start_monitoring()
        assert monitor.debugger_enabled is False
        
        # 基本网络监控仍应正常工作
        params = {
            "sessionId": "test_session",
            "requestId": "req_test", 
            "type": "XHR",
            "request": {"url": "https://test.com", "method": "GET", "headers": {}},
            "initiator": {"type": "script"},
            "timestamp": 12345.0
        }
        
        # 不应该抛出异常
        await monitor._on_request_start(params)
        
        # 事件仍应正常排队
        start_event = await event_queue.get()
        assert start_event[0] == "network_request_start"

    def test_data_format_compatibility(self, network_monitor):
        """测试数据格式向后兼容性"""
        monitor, _ = network_monitor
        
        # 验证现有的简单initiator格式完全不变
        existing_initiator = {
            "type": "script",
            "stack": {
                "callFrames": [
                    {"functionName": "legacyFunction", "url": "legacy.js", "lineNumber": 123}
                ]
            }
        }
        
        result = monitor._format_initiator_simple(existing_initiator)
        
        # 应该完全匹配现有格式
        expected = {
            "type": "script", 
            "source": {
                "function": "legacyFunction",
                "url": "legacy.js",
                "line": 123
            }
        }
        assert result == expected
        
        # 详细栈格式应该是扩展，不影响现有字段
        detailed = monitor._format_detailed_stack(existing_initiator)
        assert "frames" in detailed
        assert "asyncFrames" in detailed
        assert "truncated" in detailed
        assert isinstance(detailed["frames"], list)
        assert isinstance(detailed["asyncFrames"], list)

    @pytest.mark.asyncio
    async def test_large_upload_only_trigger(self, network_monitor):
        """测试仅大上传（小响应）的触发场景"""
        monitor, event_queue = network_monitor
        await monitor.start_monitoring()
        
        # 模拟大上传但小响应的请求
        upload_params = {
            "sessionId": "test_session",
            "requestId": "req_upload_only",
            "type": "XHR",
            "request": {
                "url": "https://api.com/upload/document",
                "method": "POST",
                "headers": {"Content-Type": "multipart/form-data"},
                "postData": "x" * (200000)  # 200KB上传
            },
            "initiator": {
                "type": "script",
                "stack": {
                    "callFrames": [
                        {"functionName": "uploadDocument", "url": "https://uploader.js", "lineNumber": 15}
                    ]
                }
            },
            "timestamp": 12345.0
        }
        
        await monitor._on_request_start(upload_params)
        
        # 验证被缓存为large_upload
        candidate = monitor.stack_candidates["req_upload_only"]
        assert candidate["initial_reason"] == "large_upload"
        
        # 模拟小响应完成（修复前这种情况不会触发详细栈）
        finish_params = {
            "sessionId": "test_session",
            "requestId": "req_upload_only",
            "encodedDataLength": 512,  # 小响应 < 100KB
            "timestamp": 12346.0
        }
        
        await monitor._on_request_finished(finish_params)
        
        # 跳过start事件，获取completion事件
        start_event = await event_queue.get()
        completion_event = await event_queue.get()
        request_data = completion_event[1]
        
        # 验证即使响应小，也因为大上传而触发详细栈
        assert "detailedStack" in request_data
        detailed_stack = request_data["detailedStack"]
        assert detailed_stack["enabled"] is True
        assert detailed_stack["reason"] == "large_upload"
        assert len(detailed_stack["frames"]) == 1
        assert detailed_stack["frames"][0]["functionName"] == "uploadDocument"