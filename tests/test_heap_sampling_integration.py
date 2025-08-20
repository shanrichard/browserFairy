"""HeapSampling集成测试"""

import asyncio
import pytest
from unittest.mock import AsyncMock
from pathlib import Path

from browserfairy.data.manager import DataManager
from browserfairy.cli import comprehensive_data_callback


class TestHeapSamplingIntegration:
    
    @pytest.fixture
    def data_manager_sync(self, tmp_path):
        """创建测试DataManager实例（同步fixture）"""
        mock_connector = AsyncMock()
        return DataManager(mock_connector, tmp_path)
    
    @pytest.mark.asyncio
    async def test_heap_sampling_data_writing(self, data_manager_sync):
        """测试heap_sampling数据写入功能"""
        data_manager = data_manager_sync
        await data_manager.start()
        test_hostname = "example.com"
        heap_data = {
            "type": "heap_sampling",
            "hostname": test_hostname,
            "targetId": "test_target",
            "sessionId": "test_session",
            "profile_summary": {
                "total_size": 1048576,
                "total_samples": 100,
                "node_count": 25,
                "max_allocation_size": 65536
            },
            "top_allocators": [
                {
                    "function_name": "allocateArray",
                    "script_url": "https://example.com/app.js",
                    "line_number": 42,
                    "self_size": 524288,
                    "sample_count": 15,
                    "allocation_percentage": 50.0
                }
            ],
            "event_id": "test_event_123"
        }
        
        # 写入heap sampling数据
        await data_manager.write_heap_sampling_data(test_hostname, heap_data)
        
        # 验证文件生成
        heap_file = data_manager.session_dir / test_hostname / "heap_sampling.jsonl"
        assert heap_file.exists(), "heap_sampling.jsonl file should be created"
        
        # 验证文件内容
        content = heap_file.read_text()
        assert "heap_sampling" in content
        assert "allocateArray" in content
        assert "524288" in content  # self_size
        
        await data_manager.stop()
    
    @pytest.mark.asyncio 
    async def test_cli_routing_integration(self, data_manager_sync):
        """测试CLI路由集成"""
        data_manager = data_manager_sync
        await data_manager.start()
        heap_event = {
            "type": "heap_sampling",
            "hostname": "test.site.com",
            "targetId": "test_target_2",
            "profile_summary": {
                "total_size": 2097152,
                "total_samples": 50,
                "node_count": 10
            },
            "top_allocators": [
                {
                    "function_name": "processData",
                    "script_url": "https://test.site.com/script.js",
                    "self_size": 1048576
                }
            ]
        }
        
        # 通过CLI回调处理数据
        await comprehensive_data_callback(data_manager, heap_event)
        
        # 验证数据正确写入
        heap_file = data_manager.session_dir / "test.site.com" / "heap_sampling.jsonl"
        assert heap_file.exists()
        
        content = heap_file.read_text()
        assert "processData" in content
        assert "1048576" in content
        
        await data_manager.stop()
    
    @pytest.mark.asyncio
    async def test_overview_json_includes_heap_sampling(self, tmp_path):
        """测试overview.json包含heap_sampling数据类型"""
        mock_connector = AsyncMock()
        data_manager = DataManager(mock_connector, tmp_path)
        await data_manager.start()
        
        # 检查overview.json
        overview_path = data_manager.session_dir / "overview.json"
        assert overview_path.exists()
        
        import json
        with open(overview_path) as f:
            overview = json.load(f)
        
        # 验证dataTypes包含heap_sampling
        assert "dataTypes" in overview
        assert "heap_sampling.jsonl" in overview["dataTypes"]
        assert overview["dataTypes"]["heap_sampling.jsonl"] == "Heap sampling profiles per hostname"
        
        await data_manager.stop()
    
    @pytest.mark.asyncio
    async def test_write_heap_sampling_data_not_running(self, tmp_path):
        """测试DataManager未运行时的优雅处理"""
        mock_connector = AsyncMock()
        data_manager = DataManager(mock_connector, tmp_path)
        # 不调用start()
        
        test_data = {
            "type": "heap_sampling",
            "hostname": "example.com",
            "profile_summary": {"total_size": 1024}
        }
        
        # 应该优雅地不写入数据
        await data_manager.write_heap_sampling_data("example.com", test_data)
        
        # 验证没有创建文件
        heap_file = data_manager.session_dir / "example.com" / "heap_sampling.jsonl"
        assert not heap_file.exists()