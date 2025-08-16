"""Tests for BrowserFairyService - TDD implementation"""

import pytest
import asyncio
import os
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from browserfairy.service import BrowserFairyService


class TestBrowserFairyService:
    @pytest.fixture
    def service(self):
        """Create a basic service instance for testing"""
        return BrowserFairyService()
    
    def test_service_initialization(self, service):
        """测试服务初始化"""
        assert service.chrome_manager is None
        assert service.exit_event is not None
        assert service.log_file is None
        
    def test_service_with_log_file(self, tmp_path):
        """测试带日志文件的服务初始化"""
        log_file = str(tmp_path / "test.log")
        service = BrowserFairyService(log_file=log_file)
        assert service.log_file == log_file
        
    def test_log_callback_creation(self, tmp_path):
        """测试日志回调功能"""
        log_file = tmp_path / "test.log"
        service = BrowserFairyService(log_file=str(log_file))
        callback = service._create_log_callback()
        
        # 测试各种事件类型的日志输出
        callback("console_error", {"message": "Test error"})
        callback("large_request", {"url": "https://example.com/api", "size_mb": 5.2})
        callback("large_response", {"url": "https://cdn.example.com/bundle.js", "size_mb": 3.1})
        callback("correlation_found", {"count": 5})
        callback("unknown_event", {"test": "data"})
        
        assert log_file.exists()
        content = log_file.read_text()
        assert "Console Error: Test error" in content
        assert "Large Request: https://example.com/api (5.2MB)" in content
        assert "Large Response: https://cdn.example.com/bundle.js (3.1MB)" in content
        assert "Correlation: 5 events correlated" in content
        assert "unknown_event: {'test': 'data'}" in content
        
    def test_log_message(self, tmp_path):
        """测试简单日志消息记录"""
        log_file = tmp_path / "test.log"
        service = BrowserFairyService(log_file=str(log_file))
        
        service._log_message("Chrome started on port 9222")
        service._log_message("Monitoring started")
        
        assert log_file.exists()
        content = log_file.read_text()
        assert "Chrome started on port 9222" in content
        assert "Monitoring started" in content
        
    def test_log_message_without_file(self):
        """测试没有日志文件时的行为"""
        service = BrowserFairyService()
        # 应该不会出错
        service._log_message("Test message")
        
    def test_log_callback_without_file(self):
        """测试没有日志文件时回调的行为"""
        service = BrowserFairyService()
        callback = service._create_log_callback()
        # 应该不会出错
        callback("console_error", {"message": "Test"})


class TestBrowserFairyServiceIntegration:
    @pytest.mark.asyncio
    async def test_chrome_instance_integration(self):
        """测试ChromeInstanceManager集成"""
        service = BrowserFairyService()
        
        # Mock ChromeInstanceManager
        with patch('browserfairy.core.chrome_instance.ChromeInstanceManager') as mock_manager_class:
            mock_manager = AsyncMock()
            mock_manager.launch_isolated_chrome.return_value = "127.0.0.1:9222"
            mock_manager.cleanup = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            # Mock monitor_comprehensive
            with patch('importlib.import_module') as mock_import:
                mock_cli_module = Mock()
                mock_monitor_func = AsyncMock(return_value=0)
                mock_cli_module.monitor_comprehensive = mock_monitor_func
                mock_import.return_value = mock_cli_module
                
                result = await service.start_monitoring()
                
                # 验证Chrome启动调用
                mock_manager.launch_isolated_chrome.assert_called_once()
                
                # 验证monitor_comprehensive调用参数
                mock_monitor_func.assert_called_once_with(
                    host="127.0.0.1",
                    port=9222,
                    duration=None,
                    status_callback=None,
                    exit_event=service.exit_event
                )
                
                # 验证清理调用
                mock_manager.cleanup.assert_called_once()
                assert result == 0

    @pytest.mark.asyncio
    async def test_chrome_instance_integration_with_log(self, tmp_path):
        """测试带日志的Chrome集成"""
        log_file = str(tmp_path / "test.log")
        service = BrowserFairyService(log_file=log_file)
        
        with patch('browserfairy.core.chrome_instance.ChromeInstanceManager') as mock_manager_class:
            mock_manager = AsyncMock()
            mock_manager.launch_isolated_chrome.return_value = "127.0.0.1:9223"
            mock_manager.cleanup = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            with patch('importlib.import_module') as mock_import:
                mock_cli_module = Mock()
                mock_monitor_func = AsyncMock(return_value=0)
                mock_cli_module.monitor_comprehensive = mock_monitor_func
                mock_import.return_value = mock_cli_module
                
                result = await service.start_monitoring(duration=60)
                
                # 验证日志记录
                log_content = Path(log_file).read_text()
                assert "Chrome started on port 9223" in log_content
                assert "Monitoring started" in log_content
                
                # 验证duration参数传递
                mock_monitor_func.assert_called_once()
                call_args = mock_monitor_func.call_args
                assert call_args[1]['duration'] == 60
                assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_on_error(self, tmp_path):
        """测试异常情况下的资源清理"""
        log_file = str(tmp_path / "test.log")
        service = BrowserFairyService(log_file=log_file)
        
        with patch('browserfairy.core.chrome_instance.ChromeInstanceManager') as mock_manager_class:
            mock_manager = AsyncMock()
            mock_manager.launch_isolated_chrome.side_effect = Exception("Chrome startup failed")
            mock_manager.cleanup = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            result = await service.start_monitoring()
            
            # 验证异常处理和清理
            assert result == 1
            mock_manager.cleanup.assert_called_once()
            
            # 验证错误日志
            log_content = Path(log_file).read_text()
            assert "ERROR: Service startup failed: Chrome startup failed" in log_content

    @pytest.mark.asyncio
    async def test_monitor_comprehensive_error_handling(self, tmp_path):
        """测试monitor_comprehensive调用异常处理"""
        log_file = str(tmp_path / "test.log")
        service = BrowserFairyService(log_file=log_file)
        
        with patch('browserfairy.core.chrome_instance.ChromeInstanceManager') as mock_manager_class:
            mock_manager = AsyncMock()
            mock_manager.launch_isolated_chrome.return_value = "127.0.0.1:9222"
            mock_manager.cleanup = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            with patch('importlib.import_module') as mock_import:
                mock_cli_module = Mock()
                mock_monitor_func = AsyncMock(side_effect=Exception("Monitor failed"))
                mock_cli_module.monitor_comprehensive = mock_monitor_func
                mock_import.return_value = mock_cli_module
                
                result = await service.start_monitoring()
                
                # 验证异常处理
                assert result == 1
                mock_manager.cleanup.assert_called_once()
                
                # 验证错误日志
                log_content = Path(log_file).read_text()
                assert "ERROR: Service startup failed: Monitor failed" in log_content


class TestCLIIntegration:
    def test_start_monitoring_cli_argument_exists(self):
        """测试CLI参数是否正确添加"""
        # 这个测试验证CLI参数解析不会出错
        from browserfairy.cli import main
        import sys
        
        # 简单验证函数存在且可导入
        from browserfairy.cli import start_monitoring_service, run_daemon_start_monitoring
        assert callable(start_monitoring_service)
        assert callable(run_daemon_start_monitoring)

    @pytest.mark.asyncio
    async def test_start_monitoring_service_function(self, tmp_path):
        """测试start_monitoring_service函数"""
        from browserfairy.cli import start_monitoring_service
        
        with patch('browserfairy.service.BrowserFairyService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.start_monitoring.return_value = 0
            mock_service_class.return_value = mock_service
            
            with patch('browserfairy.utils.paths.ensure_data_directory') as mock_ensure_dir:
                mock_data_dir = tmp_path / "BrowserFairyData"
                mock_ensure_dir.return_value = mock_data_dir
                
                # 捕获print输出进行验证
                with patch('builtins.print') as mock_print:
                    result = await start_monitoring_service()
                    
                    assert result == 0
                    mock_service.start_monitoring.assert_called_once_with(None)
                    
                    # 验证用户友好的输出
                    mock_print.assert_any_call("BrowserFairy starting comprehensive monitoring...")
                    mock_print.assert_any_call("Chrome will be launched automatically.")