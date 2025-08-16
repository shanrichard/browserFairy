"""Chrome isolated instance manager for BrowserFairy."""

import os
import sys
import tempfile
import subprocess
import socket
import shutil
import asyncio
import atexit
import logging
import urllib.parse
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class ChromeInstanceError(Exception):
    """Chrome instance management related errors."""
    pass


class ChromeStartupError(ChromeInstanceError):
    """Chrome startup related errors."""
    pass


class ChromeInstanceManager:
    """Production-grade Chrome isolated instance manager."""
    
    def __init__(self, chrome_path: Optional[str] = None, max_port_attempts: int = 5):
        self.chrome_process: Optional[subprocess.Popen] = None
        self.temp_user_data_dir: Optional[str] = None
        self.debug_port: Optional[int] = None
        self.chrome_path = chrome_path  # Support constructor override
        self.max_port_attempts = max_port_attempts
        self._cleanup_registered = False
        self._stderr_file: Optional[tempfile._TemporaryFileWrapper] = None
        
    async def launch_isolated_chrome(self) -> str:
        """Launch isolated Chrome instance, return connection address."""
        for attempt in range(self.max_port_attempts):
            try:
                # Prepare environment for each attempt (avoid port race conditions)
                await self._prepare_launch_environment(attempt)
                await self._launch_chrome_process()
                await self._wait_for_chrome_ready(timeout=15)
                
                # Register cleanup mechanism on success
                self._register_cleanup()
                return f"127.0.0.1:{self.debug_port}"
                
            except (ChromeStartupError, OSError, ConnectionError) as e:
                # Clean up resources from current attempt
                await self._cleanup_current_attempt()
                
                # Improved: Extend retry conditions, including startup timeout
                should_retry = (
                    "port" in str(e).lower() or 
                    "address already in use" in str(e).lower() or
                    "startup timeout" in str(e).lower() or  # New: startup timeout also retries
                    "connection" in str(e).lower()
                )
                
                if should_retry:
                    logger.debug(f"Chrome launch failed (attempt {attempt + 1}/{self.max_port_attempts}): {e}")
                    if attempt == self.max_port_attempts - 1:
                        raise ChromeInstanceError(f"All {self.max_port_attempts} attempts failed. Last error: {e}")
                    continue
                else:
                    # Non-retryable error, raise directly
                    raise
        
        raise ChromeInstanceError("Maximum retry attempts exceeded")
    
    async def _prepare_launch_environment(self, attempt: int):
        """Prepare launch environment (port and directory)."""
        # 1. Detect Chrome path (support environment variable override)
        if not self.chrome_path:
            self.chrome_path = self._detect_chrome_path()
            if not self.chrome_path:
                raise ChromeInstanceError("Chrome executable not found")
        
        # 2. Create isolated user data directory
        self.temp_user_data_dir = tempfile.mkdtemp(
            prefix=f"browserfairy_chrome_{attempt}_"
        )
        
        # 3. Select port (increment per attempt to avoid consecutive port conflicts)
        base_port = 9222 + (attempt * 10)
        self.debug_port = self._select_port_carefully(base_port)
    
    def _detect_chrome_path(self) -> Optional[str]:
        """Detect Chrome path with environment variable override."""
        # 1. Prefer environment variable
        env_chrome_path = os.environ.get("BROWSERFAIRY_CHROME_PATH")
        if env_chrome_path and os.path.exists(env_chrome_path) and os.access(env_chrome_path, os.X_OK):
            logger.info(f"Using Chrome path from environment: {env_chrome_path}")
            return env_chrome_path
        
        # 2. Detect system default paths
        if sys.platform == "darwin":  # macOS primary support
            possible_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
                "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
                # User installation paths
                os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ]
        elif sys.platform == "win32":  # Windows support
            possible_paths = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome Beta\Application\chrome.exe"),
                # Portable installation paths
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\chrome.exe"),
            ]
        else:
            raise ChromeInstanceError(f"Platform {sys.platform} is not supported. Please set BROWSERFAIRY_CHROME_PATH environment variable.")
        
        # Find available path
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                logger.debug(f"Found Chrome at: {path}")
                return path
        
        return None
    
    def _select_port_carefully(self, base_port: int, max_attempts: int = 10) -> int:
        """Carefully select an available port."""
        for port in range(base_port, base_port + max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                    return port
            except OSError:
                continue
        
        raise ChromeInstanceError(f"Ports {base_port}-{base_port + max_attempts - 1} are all busy. Please close other debugging applications.")
    
    async def _launch_chrome_process(self):
        """Launch Chrome process with diagnostic information preserved."""
        chrome_cmd = self._build_chrome_command()
        
        # Handle stderr based on verbose mode
        if logger.isEnabledFor(logging.DEBUG):
            # Debug mode: preserve stderr to temp file for troubleshooting
            self._stderr_file = tempfile.NamedTemporaryFile(
                mode='w+', 
                prefix='browserfairy_chrome_stderr_', 
                suffix='.log', 
                delete=False
            )
            stderr_target = self._stderr_file
            logger.debug(f"Chrome stderr will be logged to: {self._stderr_file.name}")
        else:
            # Normal mode: silent startup
            stderr_target = subprocess.DEVNULL
        
        try:
            self.chrome_process = subprocess.Popen(
                chrome_cmd,
                stdout=subprocess.DEVNULL,
                stderr=stderr_target,
                # POSIX platform independent process group for easier cleanup
                start_new_session=(os.name == 'posix')
            )
            logger.info(f"Chrome process started with PID: {self.chrome_process.pid}")
            
        except Exception as e:
            # On startup failure, try to read error information
            error_info = ""
            if hasattr(self, '_stderr_file') and self._stderr_file:
                try:
                    self._stderr_file.seek(0)
                    error_info = f"\nChrome stderr: {self._stderr_file.read()}"
                except:
                    pass
            
            raise ChromeStartupError(f"Failed to start Chrome process: {e}{error_info}")
    
    def _build_chrome_command(self) -> List[str]:
        """Build Chrome startup command (secure local binding + conservative optimization)."""
        # Basic debugging parameters - security first
        base_args = [
            f"--remote-debugging-port={self.debug_port}",
            "--remote-debugging-address=127.0.0.1",  # 🔒 Fatal fix: force local binding
            f"--user-data-dir={self.temp_user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-popup-blocking",
        ]
        
        # Conservative optimization parameters (remove potentially risky options)
        safe_optimization_args = [
            "--disable-background-networking",
            "--disable-component-update", 
            "--disable-features=Translate",
            "--disable-client-side-phishing-detection",
            "--disable-sync",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            # 🔧 Remove: --disable-ipc-flooding-protection (may reduce stability)
            # If we really encounter throughput bottlenecks, evaluate adding it separately
        ]
        
        return [self.chrome_path] + base_args + safe_optimization_args + [self._get_startup_url()]
    
    def _get_startup_url(self) -> str:
        """Get startup page URL (rigorous URL encoding)."""
        data_dir = Path.home() / "BrowserFairyData"
        
        # 🔧 Fix: Use Path.as_uri() to properly build file URL
        data_dir_uri = data_dir.as_uri()
        
        # Rigorous HTML content construction
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BrowserFairy Monitoring</title>
</head>
<body style="font-family: Arial, sans-serif; padding: 40px; text-align: center; background: #f5f5f5;">
    <h1 style="color: #2196F3;">🧚 BrowserFairy Monitoring Active</h1>
    <p style="font-size: 18px; color: #333;">Please browse normally in this Chrome window.</p>
    <p style="color: #666;">Performance data is being collected automatically.</p>
    <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">
    <h3 style="color: #555;">Quick Access:</h3>
    <p><a href="{data_dir_uri}" style="color: #2196F3; text-decoration: none;">📂 View Data Directory</a></p>
    <p><small style="color: #999;">Close this Chrome window to stop monitoring</small></p>
</body>
</html>"""
        
        # 🔧 Fix: Use correct safe character set to encode data URL
        return "data:text/html;charset=utf-8," + urllib.parse.quote(html_content, safe=':/?#[]@!$&\'()*+,;=')
    
    async def _wait_for_chrome_ready(self, timeout: int = 15):
        """Wait for Chrome to fully start and accept connections.
        
        Design points:
        - Poll http://127.0.0.1:port/json/version endpoint
        - Detection interval: every 0.5 seconds
        - HTTP timeout: 1 second timeout per request  
        - Overall timeout: raise ChromeStartupError after timeout seconds
        - Success criteria: HTTP 200 response and valid JSON format
        """
        import httpx
        
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:  # 1 second timeout per request
                    response = await client.get(f"http://127.0.0.1:{self.debug_port}/json/version")
                    if response.status_code == 200:
                        # Verify response is valid JSON
                        response.json()  # Will raise exception if not JSON
                        logger.info(f"Chrome is ready on port {self.debug_port}")
                        return
            except Exception as e:
                logger.debug(f"Chrome not ready yet: {e}")
            
            await asyncio.sleep(0.5)  # 0.5 second detection interval
        
        raise ChromeStartupError(f"Chrome startup timeout after {timeout}s")
    
    def _register_cleanup(self):
        """Register cleanup insurance mechanism.
        
        Design points:
        - Idempotency: multiple calls only register atexit hook once
        - Avoid race conditions: atexit calls synchronous version emergency cleanup
        - Process exit fallback: ensure resource cleanup even on abnormal exit
        """
        if not self._cleanup_registered:
            atexit.register(self._emergency_cleanup)  # Synchronous version avoids async race conditions
            self._cleanup_registered = True
            logger.debug("Cleanup mechanism registered")
    
    def _emergency_cleanup(self):
        """Emergency cleanup (synchronous version for atexit)."""
        try:
            # Clean up Chrome process
            if self.chrome_process and self.chrome_process.poll() is None:
                logger.warning("Emergency cleanup: terminating Chrome process")
                self.chrome_process.terminate()
                try:
                    self.chrome_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    logger.warning("Emergency cleanup: force killing Chrome process")
                    self.chrome_process.kill()
                    
            # Clean up temp directory
            if self.temp_user_data_dir and os.path.exists(self.temp_user_data_dir):
                logger.warning(f"Emergency cleanup: removing temp directory {self.temp_user_data_dir}")
                shutil.rmtree(self.temp_user_data_dir, ignore_errors=True)
                
            # 🔒 Fatal fix: close first then delete (Windows compatible)
            if hasattr(self, '_stderr_file') and self._stderr_file:
                try:
                    self._stderr_file.close()
                    os.unlink(self._stderr_file.name)
                except Exception as e:
                    logger.debug(f"Failed to cleanup stderr file in emergency: {e}")
                    
        except Exception as e:
            logger.error(f"Emergency cleanup failed: {e}")
    
    async def _cleanup_current_attempt(self):
        """Clean up resources from current attempt."""
        try:
            # Clean up process
            if self.chrome_process:
                if self.chrome_process.poll() is None:
                    self.chrome_process.terminate()
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(self.chrome_process.wait),
                            timeout=3.0
                        )
                    except asyncio.TimeoutError:
                        self.chrome_process.kill()
                self.chrome_process = None
            
            # Clean up temp directory
            if self.temp_user_data_dir and os.path.exists(self.temp_user_data_dir):
                await asyncio.to_thread(shutil.rmtree, self.temp_user_data_dir, ignore_errors=True)
                self.temp_user_data_dir = None
            
            # 🔒 Fatal fix: close first then delete (Windows compatible)
            if self._stderr_file:
                try:
                    self._stderr_file.close()
                    await asyncio.to_thread(os.unlink, self._stderr_file.name)
                    self._stderr_file = None
                except Exception as e:
                    logger.debug(f"Failed to cleanup stderr file: {e}")
                    
        except Exception as e:
            logger.debug(f"Cleanup current attempt error: {e}")
    
    def is_chrome_running(self) -> bool:
        """Check if Chrome instance is still running."""
        if self.chrome_process is None:
            return False
        
        # Check process status
        poll_result = self.chrome_process.poll()
        return poll_result is None
    
    async def wait_for_chrome_exit(self):
        """Wait for Chrome instance to exit (user closes browser)."""
        if not self.chrome_process:
            return
            
        while self.is_chrome_running():
            await asyncio.sleep(1.0)
    
    async def cleanup(self):
        """Complete resource cleanup."""
        try:
            # 1. Gracefully terminate Chrome process
            if self.chrome_process and self.chrome_process.poll() is None:
                logger.info("Gracefully terminating Chrome process...")
                self.chrome_process.terminate()
                
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.chrome_process.wait), 
                        timeout=5.0
                    )
                    logger.info("Chrome process terminated gracefully")
                except asyncio.TimeoutError:
                    logger.warning("Chrome process didn't terminate gracefully, force killing...")
                    self.chrome_process.kill()
                    await asyncio.to_thread(self.chrome_process.wait)
            
            # 2. Clean up temp user data directory
            if self.temp_user_data_dir and os.path.exists(self.temp_user_data_dir):
                logger.info(f"Cleaning up temp directory: {self.temp_user_data_dir}")
                await asyncio.to_thread(shutil.rmtree, self.temp_user_data_dir, ignore_errors=True)
            
            # 3. 🔒 Fatal fix: close first then delete stderr log file (Windows compatible)
            if hasattr(self, '_stderr_file') and self._stderr_file:
                try:
                    self._stderr_file.close()
                    await asyncio.to_thread(os.unlink, self._stderr_file.name)
                except Exception as e:
                    logger.debug(f"Failed to cleanup stderr file: {e}")
                    
            # 4. Reset state
            self.chrome_process = None
            self.temp_user_data_dir = None
            self.debug_port = None
            
            logger.info("Chrome instance cleanup completed")
            
        except Exception as e:
            logger.error(f"Cleanup error (non-fatal): {e}")
    
    # Support async context manager semantics
    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with automatic cleanup."""
        await self.cleanup()