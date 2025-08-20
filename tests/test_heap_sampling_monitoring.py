"""HeapSampling监控功能的单元测试"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from browserfairy.monitors.heap_sampling import HeapSamplingMonitor


class TestHeapSamplingMonitoring:
    
    @pytest.fixture
    def event_queue(self):
        """创建测试事件队列"""
        return asyncio.Queue()
    
    @pytest.fixture
    def heap_sampling_monitor(self, event_queue):
        """创建HeapSamplingMonitor测试实例"""
        mock_connector = AsyncMock()
        monitor = HeapSamplingMonitor(
            mock_connector, "test_session", event_queue, "test_target_id"
        )
        monitor.set_hostname("test.example.com")
        return monitor
    
    @pytest.mark.asyncio
    async def test_heap_sampling_monitor_initialization(self, heap_sampling_monitor):
        """测试HeapSampling监控器初始化"""
        # Mock HeapProfiler.enable和startSampling调用
        heap_sampling_monitor.connector.call.return_value = {}
        
        await heap_sampling_monitor.start_monitoring()
        
        # 验证必要的CDP调用
        calls = heap_sampling_monitor.connector.call.call_args_list
        call_methods = [str(call) for call in calls]
        
        assert any("HeapProfiler.enable" in call_str for call_str in call_methods)
        assert any("HeapProfiler.startSampling" in call_str for call_str in call_methods)
        assert heap_sampling_monitor.sampling_active is True
        assert heap_sampling_monitor.collection_task is not None
        
        # 清理任务
        await heap_sampling_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_heap_sampling_graceful_degradation(self, heap_sampling_monitor):
        """测试HeapSampling监控器在CDP调用失败时的优雅降级"""
        # Mock CDP调用失败
        heap_sampling_monitor.connector.call.side_effect = Exception("CDP call failed")
        
        # 不应该抛出异常
        await heap_sampling_monitor.start_monitoring()
        
        # 监控应该处于非活跃状态
        assert heap_sampling_monitor.sampling_active is False
        assert heap_sampling_monitor.collection_task is None
        
    def test_heap_profile_data_parsing(self, heap_sampling_monitor):
        """测试heap profile数据解析"""
        # 构造模拟HeapProfiler返回数据
        mock_profile = {
            "head": {
                "id": 1,
                "callFrame": {
                    "functionName": "global",
                    "url": "https://example.com/app.js",
                    "lineNumber": 1
                },
                "children": [
                    {
                        "id": 2,
                        "callFrame": {
                            "functionName": "allocateArray",
                            "url": "https://example.com/app.js",
                            "lineNumber": 45
                        },
                        "children": []
                    }
                ]
            },
            "samples": [
                {"nodeId": 2, "size": 1024},
                {"nodeId": 2, "size": 2048},
                {"nodeId": 1, "size": 512}
            ]
        }
        
        result = heap_sampling_monitor._parse_heap_profile(mock_profile)
        
        # 验证解析结果
        assert result is not None
        assert result["total_samples"] == 3
        assert result["total_size"] == 3584
        assert result["node_count"] == 2
        assert len(result["top_allocators"]) == 2
        
        # 验证热点函数排序正确
        top_allocator = result["top_allocators"][0]
        assert top_allocator["function_name"] == "allocateArray"
        assert top_allocator["self_size"] == 3072  # 1024 + 2048
        assert top_allocator["sample_count"] == 2
        assert top_allocator["allocation_percentage"] == 85.71  # 3072/3584 * 100
        
        # 验证第二个allocator
        second_allocator = result["top_allocators"][1]
        assert second_allocator["function_name"] == "global"
        assert second_allocator["self_size"] == 512
        assert second_allocator["sample_count"] == 1
    
    def test_nodes_map_building(self, heap_sampling_monitor):
        """测试节点映射构建"""
        head_node = {
            "id": 1,
            "callFrame": {"functionName": "root"},
            "children": [
                {
                    "id": 2, 
                    "callFrame": {"functionName": "child1"},
                    "children": [
                        {"id": 3, "callFrame": {"functionName": "grandchild"}, "children": []}
                    ]
                }
            ]
        }
        
        nodes_map = {}
        heap_sampling_monitor._build_nodes_map(head_node, nodes_map)
        
        assert len(nodes_map) == 3
        assert nodes_map[1]["callFrame"]["functionName"] == "root"
        assert nodes_map[2]["callFrame"]["functionName"] == "child1"
        assert nodes_map[3]["callFrame"]["functionName"] == "grandchild"
    
    def test_nodes_map_depth_limiting(self, heap_sampling_monitor):
        """测试节点映射构建的深度限制"""
        # 构造深层嵌套结构
        def create_deep_node(depth, max_depth=25):
            if depth > max_depth:
                return {"id": depth, "callFrame": {"functionName": f"deep_{depth}"}, "children": []}
            return {
                "id": depth,
                "callFrame": {"functionName": f"level_{depth}"},
                "children": [create_deep_node(depth + 1, max_depth)]
            }
        
        deep_head = create_deep_node(1)
        nodes_map = {}
        heap_sampling_monitor._build_nodes_map(deep_head, nodes_map, max_depth=20)
        
        # 应该被限制在20层深度内
        assert len(nodes_map) <= 21  # 深度0-20
        
    def test_empty_profile_handling(self, heap_sampling_monitor):
        """测试空profile数据的处理"""
        # 测试空samples
        empty_profile = {
            "head": {"id": 1, "callFrame": {"functionName": "root"}, "children": []},
            "samples": []
        }
        
        result = heap_sampling_monitor._parse_heap_profile(empty_profile)
        assert result is None
        
        # 测试缺失head
        invalid_profile = {"samples": [{"nodeId": 1, "size": 1024}]}
        result = heap_sampling_monitor._parse_heap_profile(invalid_profile)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_performance_impact(self, heap_sampling_monitor):
        """测试性能影响控制"""
        # 构造大量节点的profile数据
        large_profile = {
            "head": {"id": 1, "callFrame": {"functionName": "root"}, "children": []},
            "samples": [{"nodeId": 1, "size": 1024} for _ in range(1000)]
        }
        
        start_time = time.time()
        result = heap_sampling_monitor._parse_heap_profile(large_profile)
        end_time = time.time()
        
        # 验证解析时间合理（<100ms）
        assert end_time - start_time < 0.1
        assert result["total_samples"] == 1000
        assert result["total_size"] == 1024 * 1000
    
    def test_large_nodes_truncation(self, heap_sampling_monitor):
        """测试大量节点的截断处理"""
        # 构造超过限制的节点数
        def create_wide_node(num_children):
            children = []
            for i in range(num_children):
                children.append({
                    "id": i + 2,
                    "callFrame": {"functionName": f"child_{i}"},
                    "children": []
                })
            return {
                "id": 1,
                "callFrame": {"functionName": "root"},
                "children": children
            }
        
        # 创建1500个子节点（超过1000的限制）
        wide_head = create_wide_node(1500)
        samples = [{"nodeId": i + 1, "size": 1024} for i in range(1500)]
        
        large_profile = {
            "head": wide_head,
            "samples": samples
        }
        
        result = heap_sampling_monitor._parse_heap_profile(large_profile)
        
        # 节点数应该被限制
        assert result["node_count"] <= 1000
        # 但samples数量不受限制
        assert result["total_samples"] == 1500
    
    @pytest.mark.asyncio
    async def test_collection_task_lifecycle(self, heap_sampling_monitor):
        """测试收集任务的生命周期管理"""
        # Mock成功的CDP调用
        heap_sampling_monitor.connector.call.return_value = {}
        
        await heap_sampling_monitor.start_monitoring()
        
        # 验证任务已启动
        assert heap_sampling_monitor.collection_task is not None
        assert not heap_sampling_monitor.collection_task.done()
        
        # 停止监控
        await heap_sampling_monitor.stop_monitoring()
        
        # 验证任务已清理
        assert heap_sampling_monitor.collection_task is None
        assert heap_sampling_monitor.sampling_active is False
    
    @pytest.mark.asyncio
    async def test_event_queue_integration(self, heap_sampling_monitor, event_queue):
        """测试事件队列集成"""
        # Mock successful getSamplingProfile call
        mock_profile_response = {
            "profile": {
                "head": {
                    "id": 1,
                    "callFrame": {"functionName": "test", "url": "test.js"},
                    "children": []
                },
                "samples": [{"nodeId": 1, "size": 1024}]
            }
        }
        
        heap_sampling_monitor.connector.call.return_value = mock_profile_response
        
        # 调用收集方法
        await heap_sampling_monitor._collect_heap_profile()
        
        # 验证事件已加入队列
        assert not event_queue.empty()
        event_type, event_data = await event_queue.get()
        
        assert event_type == "heap_sampling"
        assert event_data["type"] == "heap_sampling"
        assert event_data["hostname"] == "test.example.com"
        assert event_data["targetId"] == "test_target_id"
        assert "profile_summary" in event_data
        assert "top_allocators" in event_data
        assert len(event_data["top_allocators"]) == 1
    
    def test_string_truncation(self, heap_sampling_monitor):
        """测试字符串截断功能"""
        # 构造包含长字符串的profile
        long_function_name = "a" * 200  # 200字符的函数名
        long_url = "https://example.com/" + "b" * 300  # 长URL
        
        profile = {
            "head": {
                "id": 1,
                "callFrame": {
                    "functionName": long_function_name,
                    "url": long_url,
                    "lineNumber": 42
                },
                "children": []
            },
            "samples": [{"nodeId": 1, "size": 1024}]
        }
        
        result = heap_sampling_monitor._parse_heap_profile(profile)
        
        # 验证字符串被正确截断
        allocator = result["top_allocators"][0]
        assert len(allocator["function_name"]) == 100  # 截断到100字符
        assert len(allocator["script_url"]) == 200     # 截断到200字符
        assert allocator["line_number"] == 42          # 数字字段不变