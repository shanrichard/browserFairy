"""Tests for DataManager functionality."""

import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from browserfairy.data.manager import DataManager


@pytest.mark.asyncio
class TestDataManager:
    """DataManager协调功能测试"""
    
    @pytest.fixture
    def mock_connector(self):
        """模拟ChromeConnector"""
        connector = MagicMock()
        connector.call = AsyncMock()
        return connector
    
    @pytest_asyncio.fixture
    async def data_manager(self, mock_connector, tmp_path):
        """DataManager实例，使用临时目录"""
        manager = DataManager(mock_connector, data_dir=tmp_path)
        yield manager
        # 确保清理
        try:
            await manager.stop()
        except:
            pass
    
    async def test_session_initialization(self, data_manager):
        """测试会话初始化和目录创建"""
        await data_manager.start()
        
        assert data_manager.running
        assert data_manager.session_dir.exists()
        assert (data_manager.session_dir / "overview.json").exists()
        
        # 验证overview.json内容
        overview_path = data_manager.session_dir / "overview.json"
        with open(overview_path, 'r') as f:
            overview = json.load(f)
        
        assert overview["version"] == "1.5.0"
        assert "memory_monitoring" in overview["features"]
        assert "storage_quota_monitoring" in overview["features"]
        assert "memory.jsonl" in overview["dataTypes"]
        assert "storage_global.jsonl" in overview["dataTypes"]
    
    async def test_memory_data_write_integration(self, data_manager):
        """测试内存数据写入集成"""
        await data_manager.start()
        
        memory_data = {
            "timestamp": "2025-01-14T15:30:00Z",
            "hostname": "github.com",
            "url": "https://github.com/user/repo",
            "memory": {"jsHeap": {"used": 42000000}}
        }
        
        await data_manager.write_memory_data("github.com", memory_data)
        
        # 验证文件被正确写入
        memory_file = data_manager.session_dir / "github.com" / "memory.jsonl"
        assert memory_file.exists()
        
        # 验证JSON格式
        content = memory_file.read_text().strip()
        parsed = json.loads(content)
        assert parsed["hostname"] == "github.com"
        assert parsed["memory"]["jsHeap"]["used"] == 42000000
    
    async def test_origin_tracking_from_memory_data(self, data_manager):
        """测试从内存数据触发origin跟踪"""
        await data_manager.start()
        
        memory_data = {
            "timestamp": "2025-01-14T15:30:00Z",
            "hostname": "github.com",
            "url": "https://github.com/user/repo",
            "memory": {"jsHeap": {"used": 42000000}}
        }
        
        # 监控storage_monitor的track_origin调用
        with patch.object(data_manager.storage_monitor, 'track_origin', new=AsyncMock()) as mock_track:
            await data_manager.write_memory_data("github.com", memory_data)
            
            # 验证origin跟踪被触发
            mock_track.assert_called_once_with("https://github.com")
    
    def test_extract_origin_from_url_https(self, data_manager):
        """测试HTTPS URL的origin提取"""
        url = "https://github.com/user/repo"
        origin = data_manager._extract_origin_from_url(url)
        assert origin == "https://github.com"
    
    def test_extract_origin_from_url_http(self, data_manager):
        """测试HTTP URL的origin提取"""
        url = "http://localhost:8080/path"
        origin = data_manager._extract_origin_from_url(url)
        assert origin == "http://localhost:8080"
    
    def test_extract_origin_from_url_custom_port(self, data_manager):
        """测试自定义端口的origin提取"""
        url = "https://example.com:3000/api"
        origin = data_manager._extract_origin_from_url(url)
        assert origin == "https://example.com:3000"
    
    def test_extract_origin_from_url_default_ports(self, data_manager):
        """测试默认端口的origin提取（不应包含端口号）"""
        # HTTPS默认端口443
        url = "https://example.com:443/path"
        origin = data_manager._extract_origin_from_url(url)
        assert origin == "https://example.com"
        
        # HTTP默认端口80
        url = "http://example.com:80/path"
        origin = data_manager._extract_origin_from_url(url)
        assert origin == "http://example.com"
    
    def test_extract_origin_from_url_invalid(self, data_manager):
        """测试无效URL的处理"""
        assert data_manager._extract_origin_from_url("") is None
        assert data_manager._extract_origin_from_url("invalid-url") is None
        assert data_manager._extract_origin_from_url("://no-scheme") is None
        assert data_manager._extract_origin_from_url("https://") is None
    
    async def test_storage_data_callback(self, data_manager):
        """测试存储数据回调处理"""
        await data_manager.start()
        
        quota_data = {
            "timestamp": "2025-01-14T15:30:00Z",
            "type": "storage_quota",
            "origin": "https://github.com",
            "data": {"quota": 1000000, "usage": 500000}
        }
        
        # 调用存储数据回调
        await data_manager._on_storage_data("quota", quota_data)
        
        # 验证数据被写入storage_global.jsonl
        storage_file = data_manager.session_dir / "storage_global.jsonl"
        assert storage_file.exists()
        
        content = storage_file.read_text().strip()
        parsed = json.loads(content)
        assert parsed["type"] == "storage_quota"
        assert parsed["origin"] == "https://github.com"
    
    async def test_storage_data_callback_non_quota(self, data_manager):
        """测试非quota类型的存储数据回调"""
        await data_manager.start()
        
        # 非quota类型数据应该被忽略（暂不处理）
        await data_manager._on_storage_data("indexeddb_event", {"some": "data"})
        
        # 不应该创建文件
        storage_file = data_manager.session_dir / "storage_global.jsonl"
        assert not storage_file.exists()
    
    async def test_stop_before_start(self, data_manager):
        """测试启动前停止的处理"""
        # 应该不抛出异常
        await data_manager.stop()
        assert not data_manager.running
    
    async def test_start_already_running(self, data_manager):
        """测试重复启动的处理"""
        await data_manager.start()
        assert data_manager.running
        
        # 再次启动应该直接返回
        await data_manager.start()
        assert data_manager.running
    
    async def test_write_memory_data_not_running(self, data_manager):
        """测试未运行状态下的内存数据写入"""
        memory_data = {
            "timestamp": "2025-01-14T15:30:00Z",
            "hostname": "github.com",
            "url": "https://github.com/user/repo"
        }
        
        # 未启动状态下应该直接返回，不写入文件
        await data_manager.write_memory_data("github.com", memory_data)
        
        memory_file = data_manager.session_dir / "github.com" / "memory.jsonl"
        assert not memory_file.exists()
    
    async def test_write_memory_data_no_url(self, data_manager):
        """测试无URL的内存数据写入"""
        await data_manager.start()
        
        memory_data = {
            "timestamp": "2025-01-14T15:30:00Z",
            "hostname": "github.com",
            # 无url字段
            "memory": {"jsHeap": {"used": 42000000}}
        }
        
        with patch.object(data_manager.storage_monitor, 'track_origin', new=AsyncMock()) as mock_track:
            await data_manager.write_memory_data("github.com", memory_data)
            
            # 应该仍然写入数据文件
            memory_file = data_manager.session_dir / "github.com" / "memory.jsonl"
            assert memory_file.exists()
            
            # 但不应该触发origin跟踪
            mock_track.assert_not_called()
    
    def test_session_directory_naming(self, mock_connector, tmp_path):
        """测试会话目录命名格式"""
        with patch('browserfairy.data.manager.datetime') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "2025-01-14_143022"
            
            manager = DataManager(mock_connector, data_dir=tmp_path)
            
            expected_name = "session_2025-01-14_143022"
            assert manager.session_dir.name == expected_name
            assert manager.session_dir.exists()
    
    async def test_integration_with_storage_monitor(self, data_manager):
        """测试与StorageMonitor的完整集成"""
        await data_manager.start()
        
        # 验证StorageMonitor已启动
        assert data_manager.storage_monitor.running
        
        # 验证回调已设置
        assert data_manager.storage_monitor.data_callback == data_manager._on_storage_data
        
        # 停止并验证StorageMonitor也被停止
        await data_manager.stop()
        assert not data_manager.storage_monitor.running