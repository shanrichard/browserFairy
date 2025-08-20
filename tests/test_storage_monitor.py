"""Tests for StorageMonitor functionality."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from browserfairy.monitors.storage import StorageMonitor


@pytest.mark.asyncio
class TestStorageMonitor:
    """StorageMonitor功能测试，不依赖实际Chrome"""
    
    @pytest.fixture
    def mock_connector(self):
        """模拟ChromeConnector，复用test_memory.py的模式"""
        connector = MagicMock()
        connector.call = AsyncMock()
        return connector
    
    @pytest.fixture
    def storage_monitor(self, mock_connector):
        return StorageMonitor(mock_connector)
    
    async def test_quota_collection_success(self, storage_monitor, mock_connector):
        """测试存储配额数据收集成功路径"""
        # 模拟Storage.getUsageAndQuota API返回
        mock_connector.call.return_value = {
            "quota": 1073741824,
            "usage": 567890123,
            "usageBreakdown": [
                {"storageType": "indexeddb", "usage": 234567890},
                {"storageType": "caches", "usage": 123456789}
            ]
        }
        
        origin = "https://github.com"
        quota_data = await storage_monitor._collect_quota_info(origin)
        
        assert quota_data is not None
        assert quota_data["type"] == "storage_quota"
        assert quota_data["origin"] == origin
        assert quota_data["data"]["quota"] == 1073741824
        assert quota_data["data"]["usage"] == 567890123
        assert quota_data["data"]["usageRate"] > 0.5
        assert "indexeddb" in quota_data["data"]["usageDetails"]
        assert quota_data["data"]["usageDetails"]["indexeddb"] == 234567890
        
        # 验证API调用参数
        mock_connector.call.assert_called_with(
            "Storage.getUsageAndQuota",
            {"origin": origin}
        )
    
    async def test_quota_collection_failure(self, storage_monitor, mock_connector):
        """测试配额收集失败时的优雅降级"""
        mock_connector.call.side_effect = Exception("Storage.getUsageAndQuota failed")
        
        quota_data = await storage_monitor._collect_quota_info("https://example.com")
        
        assert quota_data is None  # 失败时返回None，不抛出异常
    
    def test_calculate_warning_level(self, storage_monitor):
        """测试配额警告级别计算"""
        # Normal usage (< 75%)
        assert storage_monitor._calculate_warning_level(500, 1000) == "normal"
        
        # Warning usage (75% <= usage < 90%)
        assert storage_monitor._calculate_warning_level(800, 1000) == "warning"
        
        # Critical usage (>= 90%)
        assert storage_monitor._calculate_warning_level(950, 1000) == "critical"
        
        # Unknown when quota is 0 or invalid
        assert storage_monitor._calculate_warning_level(500, 0) == "unknown"
    
    async def test_track_origin_success(self, storage_monitor, mock_connector):
        """测试origin跟踪成功"""
        storage_monitor.running = True
        origin = "https://example.com"
        
        # Mock the quota response
        mock_connector.call.return_value = {
            "quota": 10000000,
            "usage": 5000000
        }
        
        await storage_monitor.track_origin(origin)
        
        assert origin in storage_monitor.tracked_origins
        # Check that Storage.getUsageAndQuota was called (from _collect_quota_info)
        mock_connector.call.assert_any_call(
            "Storage.getUsageAndQuota",
            {"origin": origin}
        )
    
    async def test_track_origin_already_tracked(self, storage_monitor, mock_connector):
        """测试已跟踪的origin不重复跟踪"""
        storage_monitor.running = True
        origin = "https://example.com"
        storage_monitor.tracked_origins.add(origin)
        
        await storage_monitor.track_origin(origin)
        
        # 不应该再次调用API
        mock_connector.call.assert_not_called()
    
    async def test_track_origin_not_running(self, storage_monitor, mock_connector):
        """测试未运行状态下不跟踪origin"""
        storage_monitor.running = False
        
        await storage_monitor.track_origin("https://example.com")
        
        mock_connector.call.assert_not_called()
        assert len(storage_monitor.tracked_origins) == 0
    
    async def test_track_origin_failure(self, storage_monitor, mock_connector):
        """测试origin跟踪失败的优雅处理"""
        storage_monitor.running = True
        mock_connector.call.side_effect = Exception("Tracking failed")
        
        # 不应该抛出异常
        await storage_monitor.track_origin("https://example.com")
        
        # 即使CDP调用失败，origin仍会被添加到跟踪列表（用于定期配额检查）
        assert "https://example.com" in storage_monitor.tracked_origins
    
    async def test_start_stop_lifecycle(self, storage_monitor, mock_connector):
        """测试启动停止生命周期"""
        # 初始状态
        assert not storage_monitor.running
        assert storage_monitor.quota_task is None
        
        # 启动
        await storage_monitor.start()
        assert storage_monitor.running
        assert storage_monitor.quota_task is not None
        
        # 验证start方法成功运行（不再检查Storage.enable调用，因为已被移除）
        # StorageMonitor现在依赖track_origin方法按需启用跟踪，而不是全局Storage.enable
        
        # 停止
        await storage_monitor.stop()
        assert not storage_monitor.running
        assert storage_monitor.quota_task is None
    
    async def test_storage_enable_failure_graceful(self, storage_monitor, mock_connector):
        """测试Storage.enable失败时的优雅处理"""
        mock_connector.call.side_effect = Exception("Storage.enable failed")
        
        # 应该不抛出异常
        await storage_monitor.start()
        
        # 任务应该仍然启动（Storage.enable失败不影响配额监控）
        assert storage_monitor.quota_task is not None
    
    async def test_set_data_callback(self, storage_monitor):
        """测试数据回调设置"""
        callback = MagicMock()
        storage_monitor.set_data_callback(callback)
        
        assert storage_monitor.data_callback == callback
    
    async def test_safe_callback_success(self, storage_monitor):
        """测试安全回调调用成功"""
        callback = AsyncMock()
        storage_monitor.data_callback = callback
        
        test_data = {"test": "data"}
        await storage_monitor._safe_callback("quota", test_data)
        
        callback.assert_called_once_with("quota", test_data)
    
    async def test_safe_callback_sync(self, storage_monitor):
        """测试同步回调函数"""
        callback = MagicMock()
        storage_monitor.data_callback = callback
        
        test_data = {"test": "data"}
        await storage_monitor._safe_callback("quota", test_data)
        
        callback.assert_called_once_with("quota", test_data)
    
    async def test_safe_callback_failure(self, storage_monitor):
        """测试回调失败时的优雅处理"""
        callback = AsyncMock(side_effect=Exception("Callback failed"))
        storage_monitor.data_callback = callback
        
        # 不应该抛出异常
        await storage_monitor._safe_callback("quota", {"test": "data"})
        
        callback.assert_called_once()
    
    async def test_safe_callback_no_callback(self, storage_monitor):
        """测试无回调函数时的处理"""
        storage_monitor.data_callback = None
        
        # 不应该抛出异常
        await storage_monitor._safe_callback("quota", {"test": "data"})
        
        # 测试通过没有异常即为成功
    
    async def test_quota_monitoring_loop_with_origins(self, storage_monitor, mock_connector):
        """测试配额监控循环（有跟踪的origins）"""
        # 设置模拟数据
        mock_connector.call.return_value = {
            "quota": 1000000,
            "usage": 500000,
            "usageBreakdown": []
        }
        
        storage_monitor.tracked_origins.add("https://example.com")
        storage_monitor.running = True
        
        # 设置回调
        callback = AsyncMock()
        storage_monitor.data_callback = callback
        
        # 模拟运行一次监控循环
        with pytest.MonkeyPatch.context() as m:
            # 减少睡眠时间以加快测试
            m.setattr("random.uniform", lambda a, b: 0.001)
            storage_monitor.quota_check_interval = 0.001
            
            # 启动任务
            task = asyncio.create_task(storage_monitor._quota_monitoring_loop())
            
            # 等待一小段时间让循环执行
            await asyncio.sleep(0.01)
            
            # 停止监控
            storage_monitor.running = False
            await task
        
        # 验证配额收集被调用
        assert any(
            call[0][0] == "Storage.getUsageAndQuota"
            for call in mock_connector.call.call_args_list
        )
        
        # 验证回调被调用
        callback.assert_called()
    
    async def test_quota_monitoring_loop_no_origins(self, storage_monitor):
        """测试配额监控循环（无跟踪的origins）"""
        storage_monitor.running = True
        callback = AsyncMock()
        storage_monitor.data_callback = callback
        
        # 模拟运行一次监控循环
        with pytest.MonkeyPatch.context() as m:
            m.setattr("random.uniform", lambda a, b: 0.001)
            storage_monitor.quota_check_interval = 0.001
            
            task = asyncio.create_task(storage_monitor._quota_monitoring_loop())
            await asyncio.sleep(0.01)
            storage_monitor.running = False
            await task
        
        # 没有origins时不应该调用回调
        callback.assert_not_called()