"""GC监控功能的单元测试"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from browserfairy.monitors.gc import GCMonitor


class TestGCMonitoring:
    
    @pytest.fixture
    def event_queue(self):
        """创建测试事件队列"""
        return asyncio.Queue()
    
    @pytest.fixture
    def gc_monitor(self, event_queue):
        """创建GCMonitor测试实例"""
        mock_connector = AsyncMock()
        monitor = GCMonitor(mock_connector, "test_session", event_queue)
        monitor.set_hostname("test.example.com")
        return monitor
    
    @pytest.mark.asyncio
    async def test_gc_monitor_initialization(self, gc_monitor):
        """测试GC监控器初始化"""
        # Mock Performance.enable和Runtime.enable调用
        gc_monitor.connector.call.return_value = {}
        
        await gc_monitor.start_monitoring()
        
        # 验证必要的CDP调用
        calls = gc_monitor.connector.call.call_args_list
        call_methods = [str(call) for call in calls]
        
        assert any("Performance.enable" in call_str for call_str in call_methods)
        assert any("Runtime.enable" in call_str for call_str in call_methods)
        assert gc_monitor.monitoring_active is True
    
    @pytest.mark.asyncio
    async def test_gc_monitor_graceful_degradation(self, gc_monitor):
        """测试GC监控器在CDP调用失败时的优雅降级"""
        # Mock CDP调用失败
        gc_monitor.connector.call.side_effect = Exception("CDP call failed")
        
        # 不应该抛出异常
        await gc_monitor.start_monitoring()
        
        # 监控应该处于非活跃状态
        assert gc_monitor.monitoring_active is False
    
    def test_gc_change_detection_with_counts(self, gc_monitor):
        """测试基于计数的GC变化检测"""
        # 设置基线指标
        gc_monitor.last_gc_metrics = {
            "MajorGCCount": 10,
            "MinorGCCount": 50,
            "OtherMetric": 100
        }
        
        # 模拟新指标（GC计数增加）
        current_metrics = {
            "MajorGCCount": 12,
            "MinorGCCount": 52,
            "OtherMetric": 100
        }
        
        changes = gc_monitor._detect_gc_changes(current_metrics)
        
        # 验证检测到GC事件
        assert len(changes) == 2
        
        major_gc = next((c for c in changes if c["type"] == "major"), None)
        minor_gc = next((c for c in changes if c["type"] == "minor"), None)
        
        assert major_gc is not None
        assert major_gc["count_increase"] == 2
        assert major_gc["total_count"] == 12
        assert major_gc["detected_via"] == "performance_metrics"
        
        assert minor_gc is not None
        assert minor_gc["count_increase"] == 2
        assert minor_gc["total_count"] == 52
    
    def test_gc_change_detection_with_heap_decrease(self, gc_monitor):
        """测试基于堆内存减少的GC检测"""
        # 设置基线（50MB堆内存）
        heap_size_50mb = 50 * 1024 * 1024
        heap_size_30mb = 30 * 1024 * 1024
        
        gc_monitor.last_gc_metrics = {
            "UsedJSHeapSize": heap_size_50mb,
            "MajorGCCount": 10
        }
        
        # 模拟堆内存大幅减少（可能的GC事件）
        current_metrics = {
            "UsedJSHeapSize": heap_size_30mb,  # 减少20MB
            "MajorGCCount": 10
        }
        
        changes = gc_monitor._detect_gc_changes(current_metrics)
        
        # 验证检测到堆内存减少的GC事件
        heap_gc = next((c for c in changes if c["type"] == "heap_decrease_gc"), None)
        assert heap_gc is not None
        assert heap_gc["size_decrease_mb"] == 20.0
        assert heap_gc["current_size_mb"] == 30.0
        assert heap_gc["detected_via"] == "heap_size_analysis"
    
    def test_gc_change_detection_no_baseline(self, gc_monitor):
        """测试无基线时不检测变化"""
        # 没有基线数据
        gc_monitor.last_gc_metrics = {}
        
        current_metrics = {"MajorGCCount": 10}
        
        changes = gc_monitor._detect_gc_changes(current_metrics)
        
        # 应该没有检测到变化
        assert len(changes) == 0
    
    def test_console_gc_message_extraction_positive(self, gc_monitor):
        """测试从Console消息中提取GC信息 - 正向测试"""
        test_cases = [
            {
                "args": [{"type": "string", "value": "[GC] Major collection took 45ms"}],
                "expected": "[GC] Major collection took 45ms"
            },
            {
                "args": [{"type": "string", "value": "Garbage collection started"}],
                "expected": "Garbage collection started"
            },
            {
                "args": [{"type": "string", "value": "Minor GC: 123ms"}],
                "expected": "Minor GC: 123ms"
            },
            {
                "args": [{"type": "string", "value": "SCAVENGE GC completed"}],
                "expected": "SCAVENGE GC completed"
            }
        ]
        
        for case in test_cases:
            gc_message = gc_monitor._extract_gc_info_from_console(case["args"])
            assert gc_message == case["expected"], f"Failed for {case['args']}"
    
    def test_console_gc_message_extraction_negative(self, gc_monitor):
        """测试从Console消息中提取GC信息 - 负向测试"""
        test_cases = [
            [{"type": "string", "value": "Regular log message"}],
            [{"type": "string", "value": "Network request completed"}],
            [{"type": "number", "value": 123}],  # 非字符串类型
            [],  # 空参数
            [{"type": "string", "value": ""}]  # 空字符串
        ]
        
        for args in test_cases:
            gc_message = gc_monitor._extract_gc_info_from_console(args)
            assert gc_message is None, f"Should return None for {args}"
    
    def test_console_gc_message_truncation(self, gc_monitor):
        """测试Console消息截断"""
        # 创建超长消息（600字符）
        long_message = "GC event: " + "x" * 600
        args = [{"type": "string", "value": long_message}]
        
        gc_message = gc_monitor._extract_gc_info_from_console(args)
        
        # 应该被截断到500字符
        assert gc_message is not None
        assert len(gc_message) == 500
        assert gc_message.startswith("GC event:")
    
    @pytest.mark.asyncio
    async def test_gc_event_emission(self, gc_monitor, event_queue):
        """测试GC事件发出"""
        gc_info = {
            "type": "major",
            "count_increase": 1,
            "total_count": 15,
            "detected_via": "performance_metrics"
        }
        
        await gc_monitor._emit_gc_event(gc_info)
        
        # 验证事件被加入队列
        assert not event_queue.empty()
        event_type, event_data = await event_queue.get()
        
        assert event_type == "gc"
        assert event_data["type"] == "gc_event"
        assert event_data["hostname"] == "test.example.com"
        assert "timestamp" in event_data
        assert event_data["data"]["type"] == "major"
        assert event_data["data"]["count_increase"] == 1
    
    @pytest.mark.asyncio
    async def test_status_callback_invocation(self, gc_monitor, event_queue):
        """测试状态回调调用"""
        # 设置状态回调mock
        status_callback = MagicMock()
        gc_monitor.status_callback = status_callback
        
        # 发出重要的GC事件
        gc_info = {
            "type": "major",
            "count_increase": 2,
            "total_count": 15
        }
        
        await gc_monitor._emit_gc_event(gc_info)
        
        # 验证状态回调被调用
        status_callback.assert_called_once()
        call_args = status_callback.call_args[0]
        assert call_args[0] == "gc_detected"
        assert call_args[1]["gc_type"] == "major"
        assert call_args[1]["hostname"] == "test.example.com"
    
    @pytest.mark.asyncio
    async def test_status_callback_error_handling(self, gc_monitor, event_queue):
        """测试状态回调错误处理"""
        # 设置会抛异常的状态回调
        def failing_callback(event_type, data):
            raise Exception("Callback failed")
        
        gc_monitor.status_callback = failing_callback
        
        # 发出GC事件，不应该因回调失败而崩溃
        gc_info = {"type": "major", "count_increase": 1}
        
        # 应该不抛出异常
        await gc_monitor._emit_gc_event(gc_info)
        
        # 事件仍应正常加入队列
        assert not event_queue.empty()
    
    @pytest.mark.asyncio
    async def test_queue_full_handling(self, gc_monitor):
        """测试队列满时的处理"""
        # 创建容量为1的队列并填满
        full_queue = asyncio.Queue(maxsize=1)
        full_queue.put_nowait("dummy")  # 填满队列
        gc_monitor.event_queue = full_queue
        
        gc_info = {"type": "major", "count_increase": 1}
        
        # 应该不抛出异常，优雅处理队列满的情况
        await gc_monitor._emit_gc_event(gc_info)
        
        # 队列大小应该仍然是1（事件被丢弃）
        assert full_queue.qsize() == 1
    
    @pytest.mark.asyncio
    async def test_console_message_session_filtering(self, gc_monitor):
        """测试Console消息的sessionId过滤"""
        # 设置不同sessionId的参数
        params = {
            "sessionId": "different_session",
            "args": [{"type": "string", "value": "GC event"}]
        }
        
        # 应该被过滤掉，不处理
        await gc_monitor._on_console_message(params)
        
        # 队列应该为空
        assert gc_monitor.event_queue.empty()
        
        # 设置相同sessionId的参数
        params["sessionId"] = "test_session"
        
        await gc_monitor._on_console_message(params)
        
        # 现在应该有事件了
        assert not gc_monitor.event_queue.empty()
    
    @pytest.mark.asyncio
    async def test_stop_monitoring_cleanup(self, gc_monitor):
        """测试停止监控时的清理"""
        # 启动监控
        gc_monitor.connector.call.return_value = {}
        await gc_monitor.start_monitoring()
        
        assert gc_monitor.monitoring_active is True
        
        # 停止监控
        await gc_monitor.stop_monitoring()
        
        assert gc_monitor.monitoring_active is False
        
        # 验证事件监听器被移除
        gc_monitor.connector.off_event.assert_called_once_with(
            "Runtime.consoleAPICalled", 
            gc_monitor._on_console_message
        )