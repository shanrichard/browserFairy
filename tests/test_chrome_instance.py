"""Tests for Chrome instance manager."""

import os
import sys
import tempfile
import subprocess
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

from browserfairy.core.chrome_instance import (
    ChromeInstanceManager, 
    ChromeInstanceError, 
    ChromeStartupError
)


class MockProcess:
    """Mock process for testing."""
    def __init__(self, pid=12345, returncode=None):
        self.pid = pid
        self.returncode = returncode
        self.terminated = False
        self.killed = False
    
    def poll(self):
        return self.returncode
    
    def terminate(self):
        self.terminated = True
    
    def kill(self):
        self.killed = True
        self.returncode = -9
    
    def wait(self, timeout=None):
        if self.terminated or self.killed:
            return self.returncode
        return None


@pytest.mark.asyncio
class TestChromeInstanceManager:
    """Test Chrome instance manager functionality."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        manager = ChromeInstanceManager()
        assert manager.chrome_process is None
        assert manager.temp_user_data_dir is None
        assert manager.debug_port is None
        assert manager.chrome_path is None
        assert manager.max_port_attempts == 5
        assert not manager._cleanup_registered
        assert manager._stderr_file is None

    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        chrome_path = "/custom/chrome/path"
        manager = ChromeInstanceManager(chrome_path=chrome_path, max_port_attempts=3)
        assert manager.chrome_path == chrome_path
        assert manager.max_port_attempts == 3

    def test_detect_chrome_path_environment_override(self):
        """Test Chrome path detection with environment override."""
        fake_chrome_path = "/fake/chrome/path"
        
        with patch.dict(os.environ, {"BROWSERFAIRY_CHROME_PATH": fake_chrome_path}):
            with patch('os.path.exists') as mock_exists:
                with patch('os.access') as mock_access:
                    mock_exists.return_value = True
                    mock_access.return_value = True
                    
                    manager = ChromeInstanceManager()
                    result = manager._detect_chrome_path()
                    
                    assert result == fake_chrome_path

    def test_detect_chrome_path_environment_invalid(self):
        """Test Chrome path detection with invalid environment path."""
        fake_chrome_path = "/nonexistent/chrome"
        
        with patch.dict(os.environ, {"BROWSERFAIRY_CHROME_PATH": fake_chrome_path}):
            with patch('os.path.exists') as mock_exists:
                # Make environment path fail, but let system paths fail too
                mock_exists.return_value = False
                
                manager = ChromeInstanceManager()
                result = manager._detect_chrome_path()
                assert result is None  # Should fall back to system paths but find none

    @patch('sys.platform', 'darwin')
    def test_detect_chrome_path_macos(self):
        """Test Chrome path detection on macOS."""
        expected_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        
        with patch('os.path.exists') as mock_exists:
            with patch('os.access') as mock_access:
                def exists_side_effect(path):
                    return path == expected_path
                
                mock_exists.side_effect = exists_side_effect
                mock_access.return_value = True
                
                manager = ChromeInstanceManager()
                result = manager._detect_chrome_path()
                
                assert result == expected_path

    @patch('sys.platform', 'win32')
    def test_detect_chrome_path_windows(self):
        """Test Chrome path detection on Windows."""
        expected_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        
        with patch('os.path.exists') as mock_exists:
            with patch('os.access') as mock_access:
                with patch('os.path.expandvars') as mock_expandvars:
                    def exists_side_effect(path):
                        return path == expected_path
                    
                    mock_exists.side_effect = exists_side_effect
                    mock_access.return_value = True
                    mock_expandvars.return_value = expected_path
                    
                    manager = ChromeInstanceManager()
                    result = manager._detect_chrome_path()
                    
                    assert result == expected_path

    @patch('sys.platform', 'linux')
    def test_detect_chrome_path_unsupported_platform(self):
        """Test Chrome path detection on unsupported platform."""
        manager = ChromeInstanceManager()
        
        with pytest.raises(ChromeInstanceError, match="Platform linux is not supported"):
            manager._detect_chrome_path()

    def test_select_port_carefully_success(self):
        """Test successful port selection."""
        manager = ChromeInstanceManager()
        
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            port = manager._select_port_carefully(9222)
            assert port == 9222

    def test_select_port_carefully_retry(self):
        """Test port selection with retry on conflict."""
        manager = ChromeInstanceManager()
        
        with patch('socket.socket') as mock_socket:
            mock_sock = mock_socket.return_value.__enter__.return_value
            
            # First port fails, second succeeds
            mock_sock.bind.side_effect = [OSError("Address already in use"), None]
            
            port = manager._select_port_carefully(9222)
            assert port == 9223

    def test_select_port_carefully_all_busy(self):
        """Test port selection when all ports are busy."""
        manager = ChromeInstanceManager()
        
        with patch('socket.socket') as mock_socket:
            mock_sock = mock_socket.return_value.__enter__.return_value
            mock_sock.bind.side_effect = OSError("Address already in use")
            
            with pytest.raises(ChromeInstanceError, match="are all busy"):
                manager._select_port_carefully(9222, max_attempts=3)

    def test_build_chrome_command(self):
        """Test Chrome command building."""
        manager = ChromeInstanceManager()
        manager.chrome_path = "/test/chrome"
        manager.debug_port = 9222
        manager.temp_user_data_dir = "/tmp/test"
        
        cmd = manager._build_chrome_command()
        
        assert cmd[0] == "/test/chrome"
        assert f"--remote-debugging-port=9222" in cmd
        assert "--remote-debugging-address=127.0.0.1" in cmd
        assert f"--user-data-dir=/tmp/test" in cmd
        assert "--no-first-run" in cmd
        assert "--disable-extensions" in cmd
        # Verify risky parameter is removed
        assert "--disable-ipc-flooding-protection" not in cmd

    def test_get_startup_url(self):
        """Test startup URL generation with proper encoding."""
        manager = ChromeInstanceManager()
        url = manager._get_startup_url()
        
        assert url.startswith("data:text/html;charset=utf-8,")
        # Check for encoded content - the encoding may differ slightly
        assert "BrowserFairy" in url
        assert "Monitoring" in url
        # Verify it's URL encoded (contains % characters for encoding)
        assert "%" in url

    def test_is_chrome_running_no_process(self):
        """Test Chrome running check with no process."""
        manager = ChromeInstanceManager()
        assert not manager.is_chrome_running()

    def test_is_chrome_running_process_running(self):
        """Test Chrome running check with running process."""
        manager = ChromeInstanceManager()
        manager.chrome_process = MockProcess(returncode=None)
        
        assert manager.is_chrome_running()

    def test_is_chrome_running_process_stopped(self):
        """Test Chrome running check with stopped process."""
        manager = ChromeInstanceManager()
        manager.chrome_process = MockProcess(returncode=0)
        
        assert not manager.is_chrome_running()

    async def test_wait_for_chrome_exit(self):
        """Test waiting for Chrome to exit."""
        manager = ChromeInstanceManager()
        manager.chrome_process = MockProcess(returncode=0)  # Already exited
        
        # Should return immediately
        await manager.wait_for_chrome_exit()

    def test_register_cleanup_once(self):
        """Test cleanup registration is idempotent."""
        manager = ChromeInstanceManager()
        
        with patch('atexit.register') as mock_register:
            manager._register_cleanup()
            manager._register_cleanup()  # Second call
            
            # Should only register once
            mock_register.assert_called_once()

    def test_emergency_cleanup(self):
        """Test emergency cleanup mechanism."""
        manager = ChromeInstanceManager()
        manager.temp_user_data_dir = tempfile.mkdtemp(prefix="test_emergency_")
        manager.chrome_process = MockProcess()
        
        # Create a real temp directory to test cleanup
        os.makedirs(manager.temp_user_data_dir, exist_ok=True)
        
        # Run emergency cleanup
        manager._emergency_cleanup()
        
        # Verify cleanup
        assert not os.path.exists(manager.temp_user_data_dir)
        assert manager.chrome_process.terminated

    async def test_cleanup_current_attempt(self):
        """Test cleanup of current attempt resources."""
        manager = ChromeInstanceManager()
        temp_dir = tempfile.mkdtemp(prefix="test_attempt_")
        manager.temp_user_data_dir = temp_dir
        manager.chrome_process = MockProcess()
        
        # Create a real temp directory
        os.makedirs(temp_dir, exist_ok=True)
        
        await manager._cleanup_current_attempt()
        
        # Verify cleanup
        assert not os.path.exists(temp_dir)
        assert manager.chrome_process is None

    async def test_full_cleanup(self):
        """Test complete cleanup process."""
        manager = ChromeInstanceManager()
        temp_dir = tempfile.mkdtemp(prefix="test_full_")
        manager.temp_user_data_dir = temp_dir
        manager.chrome_process = MockProcess()
        
        # Create a real temp directory
        os.makedirs(temp_dir, exist_ok=True)
        
        await manager.cleanup()
        
        # Verify state reset
        assert manager.chrome_process is None
        assert manager.temp_user_data_dir is None
        assert manager.debug_port is None
        assert not os.path.exists(temp_dir)

    @patch('subprocess.Popen')
    async def test_launch_chrome_process_success(self, mock_popen):
        """Test successful Chrome process launch."""
        manager = ChromeInstanceManager()
        manager.chrome_path = "/test/chrome"
        manager.debug_port = 9222
        manager.temp_user_data_dir = "/tmp/test"
        
        mock_process = MockProcess()
        mock_popen.return_value = mock_process
        
        await manager._launch_chrome_process()
        
        assert manager.chrome_process == mock_process
        mock_popen.assert_called_once()

    @patch('subprocess.Popen')
    async def test_launch_chrome_process_failure(self, mock_popen):
        """Test Chrome process launch failure."""
        manager = ChromeInstanceManager()
        manager.chrome_path = "/nonexistent/chrome"
        
        mock_popen.side_effect = FileNotFoundError("Chrome not found")
        
        with pytest.raises(ChromeStartupError, match="Failed to start Chrome process"):
            await manager._launch_chrome_process()

    @patch('httpx.AsyncClient')
    async def test_wait_for_chrome_ready_success(self, mock_client):
        """Test successful Chrome ready detection."""
        manager = ChromeInstanceManager()
        manager.debug_port = 9222
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Browser": "Chrome"}
        
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        
        # Should complete without timeout
        await manager._wait_for_chrome_ready(timeout=1)

    @patch('httpx.AsyncClient')
    async def test_wait_for_chrome_ready_timeout(self, mock_client):
        """Test Chrome ready detection timeout."""
        manager = ChromeInstanceManager()
        manager.debug_port = 9222
        
        # Mock failing requests
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection failed")
        )
        
        with pytest.raises(ChromeStartupError, match="Chrome startup timeout"):
            await manager._wait_for_chrome_ready(timeout=1)

    async def test_async_context_manager(self):
        """Test async context manager functionality."""
        manager = ChromeInstanceManager()
        
        # Mock cleanup method
        manager.cleanup = AsyncMock()
        
        async with manager as ctx_manager:
            assert ctx_manager is manager
        
        # Verify cleanup was called
        manager.cleanup.assert_called_once()


@pytest.mark.asyncio
class TestChromeInstanceIntegration:
    """Integration tests that require Chrome to be installed."""

    @pytest.mark.skipif(not any(
        os.path.exists(path) for path in [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]
    ), reason="Chrome not installed")
    async def test_launch_isolated_chrome_real(self):
        """Test launching real Chrome instance (integration test)."""
        manager = ChromeInstanceManager()
        
        try:
            address = await manager.launch_isolated_chrome()
            
            # Verify address format
            assert address.startswith("127.0.0.1:")
            port = int(address.split(":")[1])
            assert 9222 <= port <= 9999
            
            # Verify Chrome is running
            assert manager.is_chrome_running()
            
            # Verify connection works
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{address}/json/version")
                assert response.status_code == 200
                data = response.json()
                assert "Browser" in data
                
        finally:
            await manager.cleanup()

    @pytest.mark.skipif(not any(
        os.path.exists(path) for path in [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        ]
    ), reason="Chrome not installed")
    async def test_multiple_instances_isolation(self):
        """Test multiple Chrome instances are properly isolated."""
        manager1 = ChromeInstanceManager()
        manager2 = ChromeInstanceManager()
        
        try:
            # Launch two instances
            address1 = await manager1.launch_isolated_chrome()
            address2 = await manager2.launch_isolated_chrome()
            
            # Verify different ports
            port1 = int(address1.split(":")[1])
            port2 = int(address2.split(":")[1])
            assert port1 != port2
            
            # Verify different data directories
            assert manager1.temp_user_data_dir != manager2.temp_user_data_dir
            assert os.path.exists(manager1.temp_user_data_dir)
            assert os.path.exists(manager2.temp_user_data_dir)
            
            # Verify both instances are accessible
            async with httpx.AsyncClient() as client:
                resp1 = await client.get(f"http://{address1}/json/version")
                resp2 = await client.get(f"http://{address2}/json/version")
                assert resp1.status_code == 200
                assert resp2.status_code == 200
                
        finally:
            await manager1.cleanup()
            await manager2.cleanup()


# Additional edge case tests for expert review points

class TestExpertReviewFixes:
    """Test fixes for expert review points."""

    def test_local_binding_parameter_included(self):
        """Test that local binding parameter is included in command."""
        manager = ChromeInstanceManager()
        manager.chrome_path = "/test/chrome"
        manager.debug_port = 9222
        manager.temp_user_data_dir = "/tmp/test"
        
        cmd = manager._build_chrome_command()
        
        # Critical security fix verification
        assert "--remote-debugging-address=127.0.0.1" in cmd

    def test_stderr_file_close_before_delete(self):
        """Test stderr file is closed before deletion (Windows compatibility)."""
        manager = ChromeInstanceManager()
        
        # Create mock stderr file
        mock_stderr = MagicMock()
        manager._stderr_file = mock_stderr
        
        # Test emergency cleanup
        manager._emergency_cleanup()
        
        # Verify close was called before unlink attempt
        mock_stderr.close.assert_called_once()

    def test_url_encoding_with_special_characters(self):
        """Test URL encoding handles special characters correctly."""
        manager = ChromeInstanceManager()
        url = manager._get_startup_url()
        
        # Should not contain unencoded special characters that could break loading
        assert "<" not in url.split(",", 1)[1]  # No raw < in encoded part
        assert ">" not in url.split(",", 1)[1]  # No raw > in encoded part
        assert " " not in url.split(",", 1)[1]  # No raw spaces in encoded part

    def test_startup_timeout_triggers_retry(self):
        """Test startup timeout triggers port retry logic."""
        manager = ChromeInstanceManager(max_port_attempts=2)
        
        error_msg = "Chrome startup timeout after 15s"
        startup_error = ChromeStartupError(error_msg)
        
        # Mock the launch process to always fail with timeout
        with patch.object(manager, '_prepare_launch_environment'):
            with patch.object(manager, '_launch_chrome_process'):
                with patch.object(manager, '_wait_for_chrome_ready', side_effect=startup_error):
                    with patch.object(manager, '_cleanup_current_attempt'):
                        
                        # Should exhaust all attempts and raise final error
                        with pytest.raises(ChromeInstanceError, match="All 2 attempts failed"):
                            asyncio.run(manager.launch_isolated_chrome())