"""ConsoleMonitor与Source Map集成测试"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browserfairy.monitors.console import ConsoleMonitor


class TestConsoleMonitorWithSourceMap:
    
    @pytest.fixture
    def console_monitor(self):
        """创建ConsoleMonitor实例"""
        connector = AsyncMock()
        connector.on_event = MagicMock()
        connector.off_event = MagicMock()
        event_queue = AsyncMock()
        event_queue.put_nowait = MagicMock()
        monitor = ConsoleMonitor(connector, "test_session", event_queue)
        monitor.set_hostname("example.com")
        return monitor
    
    @pytest.mark.asyncio
    async def test_source_map_disabled_by_default(self, console_monitor):
        """测试Source Map默认关闭"""
        await console_monitor.start_monitoring()
        assert console_monitor.source_map_resolver is None
    
    @pytest.mark.asyncio
    async def test_source_map_enabled(self, console_monitor):
        """测试启用Source Map"""
        console_monitor.enable_source_map = True
        
        with patch("browserfairy.analysis.source_map.SourceMapResolver") as MockResolver:
            mock_resolver = AsyncMock()
            MockResolver.return_value = mock_resolver
            mock_resolver.initialize.return_value = True
            
            await console_monitor.start_monitoring()
            
            assert console_monitor.source_map_resolver is not None
            mock_resolver.initialize.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_backward_compatibility(self, console_monitor):
        """测试字段向后兼容性"""
        # 触发异常事件
        params = {
            "sessionId": "test_session",
            "exceptionDetails": {
                "text": "Test error",
                "stackTrace": {
                    "callFrames": [{
                        "functionName": "test",
                        "scriptId": "123",
                        "url": "https://example.com/app.js",
                        "lineNumber": 10,
                        "columnNumber": 20
                    }]
                }
            }
        }
        
        await console_monitor._on_exception_thrown(params)
        
        # 验证队列中的数据
        call_args = console_monitor.event_queue.put_nowait.call_args
        event_type, event_data = call_args[0][0]
        
        # 验证保留了原字段名
        stack_frame = event_data["stackTrace"][0]
        assert "function" in stack_frame  # 原字段
        assert stack_frame["function"] == "test"
        assert "url" in stack_frame       # 原字段
        assert "line" in stack_frame      # 原字段
        assert stack_frame["line"] == 10
        assert "column" in stack_frame    # 原字段
        assert stack_frame["column"] == 20
        
        # 验证新增了字段
        assert "scriptId" in stack_frame
        assert stack_frame["scriptId"] == "123"
        assert "lineNumber" in stack_frame
        assert stack_frame["lineNumber"] == 10
        assert "columnNumber" in stack_frame
        assert stack_frame["columnNumber"] == 20
    
    @pytest.mark.asyncio
    async def test_exception_with_source_map(self, console_monitor):
        """测试异常事件的Source Map增强"""
        console_monitor.enable_source_map = True
        console_monitor.source_map_resolver = AsyncMock()
        
        # 模拟增强后的堆栈（保持字段兼容）
        enhanced_stack = [{
            "function": "test",  # 保留原字段
            "url": "https://example.com/app.js",
            "line": 1,
            "column": 100,
            "scriptId": "123",
            "lineNumber": 1,
            "columnNumber": 100,
            "original": {  # 仅新增original字段
                "file": "source.js",
                "line": 45,
                "column": 10
            }
        }]
        console_monitor.source_map_resolver.resolve_stack_trace.return_value = enhanced_stack
        
        # 触发异常事件
        params = {
            "sessionId": "test_session",
            "exceptionDetails": {
                "text": "Test error",
                "stackTrace": {
                    "callFrames": [{
                        "functionName": "test",
                        "scriptId": "123",
                        "url": "https://example.com/app.js",
                        "lineNumber": 1,
                        "columnNumber": 100
                    }]
                }
            }
        }
        
        await console_monitor._on_exception_thrown(params)
        
        # 验证调用了source map解析
        console_monitor.source_map_resolver.resolve_stack_trace.assert_called_once()
        
        # 验证结果包含original字段
        call_args = console_monitor.event_queue.put_nowait.call_args
        event_type, event_data = call_args[0][0]
        assert "original" in event_data["stackTrace"][0]
    
    @pytest.mark.asyncio
    async def test_source_map_resolution_failure(self, console_monitor):
        """测试Source Map解析失败时的降级"""
        console_monitor.enable_source_map = True
        console_monitor.source_map_resolver = AsyncMock()
        console_monitor.source_map_resolver.resolve_stack_trace.side_effect = Exception("Parse error")
        
        params = {
            "sessionId": "test_session",
            "exceptionDetails": {
                "text": "Test error",
                "stackTrace": {
                    "callFrames": [{
                        "functionName": "test",
                        "scriptId": "123",
                        "url": "https://example.com/app.js",
                        "lineNumber": 1,
                        "columnNumber": 100
                    }]
                }
            }
        }
        
        await console_monitor._on_exception_thrown(params)
        
        # 验证即使解析失败，事件仍然被处理
        console_monitor.event_queue.put_nowait.assert_called_once()
        
        # 验证堆栈保持原样（没有original字段）
        call_args = console_monitor.event_queue.put_nowait.call_args
        event_type, event_data = call_args[0][0]
        assert "original" not in event_data["stackTrace"][0]

    @pytest.mark.asyncio
    async def test_source_map_resolution_timeout(self, console_monitor, monkeypatch):
        """当解析超时时应保持原堆栈并继续上报"""
        console_monitor.enable_source_map = True
        console_monitor.source_map_resolver = AsyncMock()
        # 让 asyncio.wait_for 在解析时超时
        import asyncio as _asyncio
        monkeypatch.setattr(_asyncio, 'wait_for', MagicMock(side_effect=_asyncio.TimeoutError))

        params = {
            "sessionId": "test_session",
            "exceptionDetails": {
                "text": "Test error",
                "stackTrace": {
                    "callFrames": [{
                        "functionName": "test",
                        "scriptId": "123",
                        "url": "https://example.com/app.js",
                        "lineNumber": 1,
                        "columnNumber": 100
                    }]
                }
            }
        }

        await console_monitor._on_exception_thrown(params)

        # 验证事件被正常入队
        console_monitor.event_queue.put_nowait.assert_called_once()
        # 验证堆栈保持原样（没有original字段）
        call_args = console_monitor.event_queue.put_nowait.call_args
        event_type, event_data = call_args[0][0]
        assert "original" not in event_data["stackTrace"][0]
    
    @pytest.mark.asyncio
    async def test_cleanup_source_map_resolver(self, console_monitor):
        """测试清理Source Map解析器"""
        console_monitor.enable_source_map = True
        
        with patch("browserfairy.analysis.source_map.SourceMapResolver") as MockResolver:
            mock_resolver = AsyncMock()
            MockResolver.return_value = mock_resolver
            mock_resolver.initialize.return_value = True
            
            await console_monitor.start_monitoring()
            await console_monitor.stop_monitoring()
            
            # 验证调用了cleanup
            mock_resolver.cleanup.assert_called_once()
            assert console_monitor.source_map_resolver is None
    
    @pytest.mark.asyncio
    async def test_console_monitor_set_hostname(self, console_monitor):
        """测试ConsoleMonitor设置hostname到source map resolver"""
        console_monitor.enable_source_map = True
        console_monitor.set_hostname("test.example.com")
        
        with patch("browserfairy.analysis.source_map.SourceMapResolver") as MockResolver:
            mock_resolver = MagicMock()
            MockResolver.return_value = mock_resolver
            mock_resolver.initialize = AsyncMock(return_value=True)
            mock_resolver.set_hostname = MagicMock()
            
            await console_monitor.start_monitoring()
            
            # 验证set_hostname被调用
            mock_resolver.set_hostname.assert_called_once_with("test.example.com")
    
    @pytest.mark.asyncio
    async def test_console_monitor_set_hostname_no_hostname(self, console_monitor):
        """测试ConsoleMonitor无hostname时不调用set_hostname"""
        console_monitor.enable_source_map = True
        # 清除fixture设置的hostname
        console_monitor.hostname = None
        
        with patch("browserfairy.analysis.source_map.SourceMapResolver") as MockResolver:
            mock_resolver = MagicMock()
            MockResolver.return_value = mock_resolver
            mock_resolver.initialize = AsyncMock(return_value=True)
            mock_resolver.set_hostname = MagicMock()
            
            await console_monitor.start_monitoring()
            
            # 验证set_hostname没有被调用
            mock_resolver.set_hostname.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_backward_compatibility_unchanged(self, console_monitor):
        """测试完全向后兼容 - 无构造函数参数变化"""
        # 验证现有的ConsoleMonitor构造函数仍然工作
        connector = AsyncMock()
        connector.on_event = MagicMock()
        event_queue = AsyncMock()
        
        # 创建ConsoleMonitor实例，使用原有的参数
        from browserfairy.monitors.console import ConsoleMonitor
        monitor = ConsoleMonitor(connector, "test_session", event_queue)
        
        # 验证基本属性正确设置
        assert monitor.connector == connector
        assert monitor.session_id == "test_session" 
        assert monitor.event_queue == event_queue
        assert monitor.enable_source_map == False  # 默认值
        
        # 验证可以正常启动监控
        await monitor.start_monitoring()
        
        # 验证事件处理器被正确注册
        connector.on_event.assert_any_call("Runtime.consoleAPICalled", monitor._on_console_message)
        connector.on_event.assert_any_call("Runtime.exceptionThrown", monitor._on_exception_thrown)
