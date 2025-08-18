"""网络请求调用栈关联功能的单元测试"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from browserfairy.monitors.network import NetworkMonitor


class TestNetworkStackEnhancement:
    
    @pytest.fixture 
    def enhanced_network_monitor(self):
        """创建启用栈增强的NetworkMonitor"""
        mock_connector = AsyncMock()
        event_queue = asyncio.Queue()
        monitor = NetworkMonitor(mock_connector, "test_session", event_queue)
        return monitor
    
    def test_should_cache_initiator_large_upload(self, enhanced_network_monitor):
        """测试大上传（>100KB）触发缓存"""
        params = {
            "type": "XHR",
            "requestId": "req123",
            "request": {
                "url": "https://api.com/upload",
                "postData": "x" * (102400 + 1)  # 100KB + 1
            }
        }
        result = enhanced_network_monitor._should_cache_initiator(params)
        assert result == "large_upload"
    
    def test_should_cache_initiator_xhr_fetch(self, enhanced_network_monitor):
        """测试XHR/Fetch请求触发缓存"""
        params = {"type": "XHR", "request": {"url": "https://api.com/data"}}
        assert enhanced_network_monitor._should_cache_initiator(params) == "xhr_fetch_candidate"
        
        params = {"type": "Fetch", "request": {"url": "https://api.com/data"}}
        assert enhanced_network_monitor._should_cache_initiator(params) == "xhr_fetch_candidate"
    
    def test_should_cache_initiator_script_with_stack(self, enhanced_network_monitor):
        """测试有JS栈的Script触发缓存"""
        params = {
            "type": "Script",
            "request": {"url": "https://cdn.com/dynamic.js"},
            "initiator": {"stack": {"callFrames": [{"functionName": "loadScript"}]}}
        }
        assert enhanced_network_monitor._should_cache_initiator(params) == "script_with_stack"
        
        # 无栈的Script不缓存
        params["initiator"] = {"type": "parser"}
        assert enhanced_network_monitor._should_cache_initiator(params) is None
    
    def test_confirm_detailed_stack_large_download(self, enhanced_network_monitor):
        """测试大下载确认"""
        params = {"encodedDataLength": 102401}  # 100KB + 1
        assert enhanced_network_monitor._confirm_detailed_stack_needed("https://api.com/export", params) == "large_download"
    
    def test_confirm_detailed_stack_high_frequency_api(self, enhanced_network_monitor):
        """测试高频API确认"""
        # 设置API计数
        enhanced_network_monitor.api_count[("https://api.com", "/v2/trades")] = 55
        params = {"encodedDataLength": 1000}
        result = enhanced_network_monitor._confirm_detailed_stack_needed("https://api.com/v2/trades", params)
        assert result == "high_frequency_api_55"
    
    def test_should_not_collect_for_normal_requests(self, enhanced_network_monitor):
        """测试正常请求不触发详细栈"""
        # 小文件（不构成大上传候选）
        params = {"type": "XHR", "request": {"url": "https://api.com/status", "postData": "small"}}
        assert enhanced_network_monitor._should_cache_initiator(params) == "xhr_fetch_candidate"
        # 完成阶段长度不达标 → 不触发
        assert enhanced_network_monitor._confirm_detailed_stack_needed("https://api.com/status", {"encodedDataLength": 1000}) is None
        
    def test_traverse_async_stack_with_parent(self, enhanced_network_monitor):
        """测试异步栈遍历"""
        initiator = {
            "stack": {
                "callFrames": [{"functionName": "main", "url": "main.js", "lineNumber": 1}],
                "parent": {
                    "callFrames": [{"functionName": "async_parent", "url": "async.js", "lineNumber": 10}]
                }
            }
        }
        result = enhanced_network_monitor._format_detailed_stack(initiator)
        assert len(result["frames"]) == 1
        assert len(result["asyncFrames"]) == 1
        assert result["asyncFrames"][0]["functionName"] == "async_parent"
        
    def test_stack_depth_limitation(self, enhanced_network_monitor):
        """测试栈深度限制（主栈≤30，父链≤15）"""
        # 构造深栈
        deep_frames = [
            {"functionName": f"func{i}", "url": "deep.js", "lineNumber": i}
            for i in range(40)  # 40层深度，应该被限制到30
        ]
        
        initiator = {
            "type": "script",
            "stack": {
                "callFrames": deep_frames
            }
        }
        
        # 测试trim方法
        trimmed = enhanced_network_monitor._trim_initiator_snapshot(initiator)
        assert len(trimmed["stack"]["callFrames"]) == 30  # 应该被限制到30
        
        # 测试format方法
        result = enhanced_network_monitor._format_detailed_stack(trimmed)
        assert len(result["frames"]) == 30
        assert result["truncated"] is True
        
    @pytest.mark.asyncio
    async def test_debugger_enable_graceful_failure(self, enhanced_network_monitor):
        """测试Debugger启用失败的优雅处理"""
        # Mock Debugger.enable失败
        enhanced_network_monitor.connector.call.side_effect = Exception("Debugger unavailable")
        
        await enhanced_network_monitor._enable_debugger_globally()
        
        # 应该优雅失败，不抛出异常
        assert enhanced_network_monitor.debugger_enabled is False
        
    def test_existing_functionality_unchanged(self, enhanced_network_monitor):
        """测试现有简单initiator功能完全不变"""
        initiator = {
            "type": "script",
            "stack": {
                "callFrames": [
                    {"functionName": "existing", "url": "existing.js", "lineNumber": 42}
                ]
            }
        }
        result = enhanced_network_monitor._format_initiator_simple(initiator)
        
        # 验证现有格式完全不变
        expected = {
            "type": "script",
            "source": {
                "function": "existing",
                "url": "existing.js",
                "line": 42
            }
        }
        assert result == expected

    def test_parse_origin_path(self, enhanced_network_monitor):
        """测试URL解析功能"""
        # 测试基本URL
        origin, path = enhanced_network_monitor._parse_origin_path("https://api.com/v2/trades?param=1")
        assert origin == "https://api.com"
        assert path == "/v2/trades"
        
        # 测试根路径
        origin, path = enhanced_network_monitor._parse_origin_path("https://example.com")
        assert origin == "https://example.com"
        assert path == "/"
        
    def test_cache_trimmed_initiator(self, enhanced_network_monitor):
        """测试initiator缓存功能"""
        initiator = {
            "type": "script",
            "stack": {
                "callFrames": [{"functionName": "test", "url": "test.js", "lineNumber": 1}]
            }
        }
        
        enhanced_network_monitor._cache_trimmed_initiator(
            "req123", initiator, "https://test.com", "XHR", "test_reason"
        )
        
        assert "req123" in enhanced_network_monitor.stack_candidates
        candidate = enhanced_network_monitor.stack_candidates["req123"]
        assert candidate["url"] == "https://test.com"
        assert candidate["resource_type"] == "XHR"
        assert "snapshot" in candidate

    def test_update_request_counts(self, enhanced_network_monitor):
        """测试请求计数更新"""
        # XHR请求应该更新api_count
        params = {
            "type": "XHR",
            "request": {"url": "https://api.com/endpoint"}
        }
        enhanced_network_monitor._update_request_counts(params)
        assert enhanced_network_monitor.api_count[("https://api.com", "/endpoint")] == 1
        
        # Script请求应该更新resource_count
        params = {
            "type": "Script",
            "request": {"url": "https://cdn.com/app.js"}
        }
        enhanced_network_monitor._update_request_counts(params)
        assert enhanced_network_monitor.resource_count[("https://cdn.com", "/app.js")] == 1

    def test_get_debug_stats(self, enhanced_network_monitor):
        """测试调试统计获取"""
        # 添加一些数据
        enhanced_network_monitor.stack_candidates["test"] = {"test": "data"}
        enhanced_network_monitor.api_count[("test", "/test")] = 1
        enhanced_network_monitor._debug_stats["total_stacks_collected"] = 5
        
        stats = enhanced_network_monitor.get_debug_stats()
        
        assert stats["candidates_cached"] == 1
        assert stats["api_count_entries"] == 1
        assert stats["debugger_enabled"] is False
        assert stats["lifetime_stats"]["total_stacks_collected"] == 5
        assert "recent_triggers" in stats

    def test_large_upload_trigger_priority(self, enhanced_network_monitor):
        """测试大上传触发优先级（修复后）"""
        # 创建大上传候选并保存initial_reason
        enhanced_network_monitor._cache_trimmed_initiator(
            "req_upload", {"type": "script"}, "https://api.com/upload", "XHR", "large_upload"
        )
        
        # 小响应：应该因为initial_reason="large_upload"而触发
        candidate = enhanced_network_monitor.stack_candidates["req_upload"]
        result = enhanced_network_monitor._confirm_detailed_stack_needed(
            "https://api.com/upload", {"encodedDataLength": 1000}, candidate
        )
        assert result == "large_upload"
        
        # 大响应：应该优先返回large_download而不是large_upload
        result_big = enhanced_network_monitor._confirm_detailed_stack_needed(
            "https://api.com/upload", {"encodedDataLength": 200000}, candidate  # 200KB
        )
        assert result_big == "large_download"  # 大下载优先级更高

    def test_css_resource_counting(self, enhanced_network_monitor):
        """测试CSS资源计数（修复后）"""
        # CSS文件应该被计入resource_count
        params = {
            "type": "Script",
            "request": {"url": "https://cdn.com/styles.css"}
        }
        enhanced_network_monitor._update_request_counts(params)
        assert enhanced_network_monitor.resource_count[("https://cdn.com", "/styles.css")] == 1

    def test_initial_reason_preservation(self, enhanced_network_monitor):
        """测试初始reason被正确保存"""
        enhanced_network_monitor._cache_trimmed_initiator(
            "req_test", {"type": "script"}, "https://test.com", "XHR", "large_upload"
        )
        
        candidate = enhanced_network_monitor.stack_candidates["req_test"]
        assert candidate["initial_reason"] == "large_upload"
        assert candidate["url"] == "https://test.com"
        assert candidate["resource_type"] == "XHR"

    def test_record_trigger_event(self, enhanced_network_monitor):
        """测试触发事件记录"""
        enhanced_network_monitor._record_trigger_event("large_download", "req123", "https://test.com", True)
        
        assert len(enhanced_network_monitor._recent_triggers) == 1
        trigger = enhanced_network_monitor._recent_triggers[0]
        assert trigger["reason"] == "large_download"
        assert trigger["enabled"] is True
        assert trigger["requestId"] == "req123"


# Mock数据用于测试
MOCK_COMPLEX_STACK = {
    "type": "script",
    "stack": {
        "callFrames": [
            {
                "functionName": "ComponentA.fetchLargeData", 
                "scriptId": "123",
                "url": "https://app.js",
                "lineNumber": 42,
                "columnNumber": 15
            },
            {
                "functionName": "ComponentA.init",
                "scriptId": "123", 
                "url": "https://app.js",
                "lineNumber": 28,
                "columnNumber": 8
            }
        ],
        "parent": {
            "callFrames": [
                {
                    "functionName": "setTimeout",
                    "scriptId": "124",
                    "url": "https://scheduler.js", 
                    "lineNumber": 89,
                    "columnNumber": 12
                }
            ]
        }
    }
}